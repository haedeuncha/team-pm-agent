# 데이터 명세서 — Team Project PM Agent

> 수집기(`pm_agent/collector`)가 GitHub에서 무엇을 가져와 어떤 형태로 그래프에 넘기는지 정의합니다.
> 관련 문서: [REQUIREMENTS](REQUIREMENTS.md) · [AGENTS](AGENTS.md)

## 1. 수집 기간 (Window)

| 실행 방식 | `since` | `until` |
|---|---|---|
| cron (화~금) | 직전 **성공한** daily-scrum 실행 시각 | 현재 시각 |
| cron (월) | 같은 규칙 → 자동으로 금요일 실행 이후가 됨 | 현재 시각 |
| 직전 실행 기록이 없음 | 현재 − 24시간 (월요일은 − 72시간) | 현재 시각 |
| 수동 `since=7d` | 현재 − 7일 | 현재 시각 |

- 직전 성공 시각은 pm-agent 저장소 자신의 실행 기록에서 조회합니다(상태 저장 없이 FR-04 충족).
  `GET /repos/haedeuncha/team-pm-agent/actions/workflows/daily-scrum.yml/runs?status=success&per_page=1`
- 내부 시각은 모두 **UTC ISO 8601**로 다루고, 리포트에 표시할 때만 KST로 바꿉니다.

## 2. 호출하는 GitHub REST API

공통 헤더: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Authorization: Bearer $GH_READ_TOKEN`
페이지네이션: `per_page=100`, 응답의 `Link` 헤더에 `rel="next"`가 있으면 계속 요청합니다.

| # | 목적 | Endpoint | 주요 파라미터 | 비고 |
|---|---|---|---|---|
| A1 | 기본 브랜치 커밋 | `GET /repos/{o}/{r}/commits` | `since`, `until` | 기본 브랜치만 조회됨 |
| A2 | PR 목록 | `GET /repos/{o}/{r}/pulls` | `state=all&sort=updated&direction=desc` | `updated_at < since`가 나오면 중단 |
| A3 | PR 커밋 | `GET /repos/{o}/{r}/pulls/{n}/commits` | — | 기능 브랜치 작업을 잡기 위해 A2에서 걸린 PR만 조회 |
| A4 | PR 리뷰 | `GET /repos/{o}/{r}/pulls/{n}/reviews` | — | 오래된 PR 판정, "리뷰 남김" 집계 |
| A5 | 리뷰 요청자 | `GET /repos/{o}/{r}/pulls/{n}/requested_reviewers` | — | 오늘 할 일 |
| A6 | 이슈 | `GET /repos/{o}/{r}/issues` | `state=all&since=` | 응답에 PR도 섞여 있으므로 `pull_request` 키가 있으면 제외 |
| A7 | 열린 할당 이슈 | `GET /repos/{o}/{r}/issues` | `state=open&assignee={login}` | 팀원별로 호출, 기간 무관 |
| A8 | CI 실행 | `GET /repos/{o}/{r}/actions/runs` | `created=>={since 날짜}` | 반복 실패 판정을 위해 **최근 20회**는 기간과 무관하게 추가 조회 |
| A9 | CI job | `GET /repos/{o}/{r}/actions/runs/{id}/jobs` | — | 실패한 run만 조회 |
| A11 | 이슈 이벤트 | `GET /repos/{o}/{r}/issues/{n}/events` | — | 열린 할당 이슈의 마지막 `assigned` 시각 (막힌 작업 판정) |
| A12 | 담당자 없는 버그 | `GET /repos/{o}/{r}/issues` | `state=open&labels=bug&assignee=none` | 기간 무관 |
| A10 | job 로그 | `GET /repos/{o}/{r}/actions/jobs/{id}/logs` | — | 실패한 job만, 302 리다이렉트를 따라감. **마지막 200줄만 저장** |

보안: 수집 직후 커밋 메시지·PR/이슈 제목·CI 로그에서 비밀값을 가립니다(`pm_agent/security.py`, OPERATIONS 8장).

예상 호출 수(4인 팀, 1일): A1~A6 약 30회 + A7 4회 + A8~A10 약 20회 ≈ **60회** (NFR-09 기준 300회 이하)

## 3. 정규화된 데이터 모델

수집기는 GitHub 원본 JSON을 그대로 넘기지 않고, 아래 Pydantic 모델로 줄여서 넘깁니다(LLM 토큰 절약, NFR-08).

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

class Commit(BaseModel):
    sha: str                 # 앞 7자리
    author: str | None       # 팀원 key (config 매핑 결과), 매핑 실패 시 None
    message: str             # 첫 줄만
    committed_at: datetime
    url: str
    issue_refs: list[int]    # 메시지 속 "#41" 같은 참조

class Review(BaseModel):
    reviewer: str
    state: Literal["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"]
    submitted_at: datetime

class PullRequest(BaseModel):
    number: int
    title: str
    author: str
    state: Literal["open", "closed", "merged"]
    draft: bool
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    requested_reviewers: list[str]
    reviews: list[Review]
    commits: list[Commit]
    closes_issues: list[int] # 본문의 "Closes #41" 등
    url: str

class Issue(BaseModel):
    number: int
    title: str
    state: Literal["open", "closed"]
    labels: list[str]
    assignees: list[str]
    created_at: datetime
    closed_at: datetime | None
    closed_by: str | None
    assigned_at: datetime | None           # A11 마지막 assigned 이벤트
    last_linked_activity: datetime | None  # 이 이슈를 참조한 커밋/PR의 마지막 활동 (최근 3일 커밋 기준)
    url: str

class CIJob(BaseModel):
    job_id: int
    name: str
    conclusion: str | None
    failed_step: str | None
    failed_tests: list[str]  # 로그 파싱 결과 (4장)
    log_tail: str            # 마지막 200줄

class CIRun(BaseModel):
    run_id: int
    run_number: int
    workflow: str
    branch: str
    head_sha: str
    event: str
    conclusion: str | None   # success, failure, cancelled, skipped, timed_out, action_required, neutral 등
                             # (규칙은 success/failure 만 사용. 실데이터에서 action_required 확인)
    created_at: datetime
    actor: str | None
    jobs: list[CIJob]        # 실패한 run만 채움
    url: str

class RawActivity(BaseModel):
    repo: str
    default_branch: str
    since: datetime
    until: datetime
    commits: list[Commit]
    pull_requests: list[PullRequest]
    issues: list[Issue]
    open_assigned: dict[str, list[Issue]]   # 팀원 key → 열린 할당 이슈
    open_unassigned_bugs: list[Issue]       # A12
    ci_runs: list[CIRun]                    # 기간 내 + 최근 20회
    unmapped_commits: int                   # 팀원 매핑에 실패한 커밋 수
```

> 구현: `pm_agent/models.py`, `pm_agent/collector/`. 막힌 작업 판정을 위해 커밋은 `min(since, now-3일)`부터 가져오고, 리포트의 "어제 한 일"에는 기간 안의 커밋만 씁니다.

## 4. 실패한 테스트 이름 추출

팀 프로젝트의 테스트 도구에 맞춰 `config.yaml`에서 정규식을 고릅니다.

| 도구 | 정규식 | 예시 |
|---|---|---|
| pytest | `^FAILED (\S+::\S+)` | `FAILED tests/test_auth.py::test_refresh` |
| Jest | `^\s*● (.+?) › (.+)$` | `● AuthService › refreshes token` |
| JUnit/Gradle | `^(\S+) > (\S+) FAILED$` | `AuthTest > refresh() FAILED` |

- 추출에 실패하면 `failed_tests=[]`로 두고 `failed_step` 이름으로 대신 판정합니다.
- ANSI 색상 코드와 타임스탬프 접두어(`2026-09-30T00:07:12.3Z `)는 파싱 전에 제거합니다.

## 5. 팀원 매핑 (`config.yaml`)

> 전체 설정 항목(여러 저장소, 채널, 근무일, 상태 저장소, 보안)은 `config.yaml` 주석과 [OPERATIONS.md](OPERATIONS.md)를 보세요. 아래는 팀원 매핑 부분입니다.

```yaml
repos:
  - name: owner/team-repo
    alias: ""
timezone: Asia/Seoul
leader: haeden                     # members 의 key
members:
  haeden:
    display: 해든
    github: haedeuncha
    emails: [haeden@example.com]   # 커밋 author 매칭용, LLM에는 보내지 않음 (실제 값은 Secret/Variable로)
  minsu:
    display: 민수
    github: minsu-kim
    emails: []
bots: [dependabot[bot], github-actions[bot]]   # 집계에서 제외
test_log_pattern: pytest
```

매칭 순서: ① 커밋의 `author.login` → ② `commit.author.email` → ③ 실패 시 `author=None`, 리포트에 "매핑되지 않은 커밋 N건"으로 표시.

## 6. 팀원별 근거 데이터 (`MemberDigest`)

요약 Agent는 이 구조 **안에 있는 항목만** 쓸 수 있습니다(AGENTS 5장).

```python
class EvidenceItem(BaseModel):
    ref: str        # "commit:a1b2c3d", "pr:37", "issue:41", "run:142"
    kind: Literal["commit", "pr_merged", "pr_opened", "review", "issue_closed",
                  "issue_assigned", "review_requested", "draft_pr"]
    title: str
    url: str

class MemberDigest(BaseModel):
    member: str
    yesterday: list[EvidenceItem]   # FR-05
    today: list[EvidenceItem]       # FR-06
```

`ref` 형식은 모든 문서와 코드에서 이 규칙으로 통일합니다. 저장소가 여러 개면 별칭을 붙여 `pr:web/35`, `commit:api/a1b2c3d`, `run:api/144`처럼 씁니다(리포트에는 `web#35`, `api@a1b2c3d`, `api run #144`로 표시). 검증기(AGENTS 6장)는 `ref`가 `RawActivity` 안에 실제로 있는지 확인합니다.

## 7. Fixtures

가상 팀 **campus-market**(캠퍼스 중고거래 앱)의 시나리오입니다. `python scripts/make_fixtures.py`로 다시 만들 수 있습니다.

| 팀원 key | 이름 | GitHub (가상) | 담당 |
|---|---|---|---|
| haeden | 해든 (팀장) | haedeuncha | 인증 |
| minsu | 민수 | minsu-dev | 결제 |
| jiwoo | 지우 | jiwoo-lee | 프론트엔드 |
| seoyeon | 서연 | seoyeon-park | 채팅·알림 |

| 파일 | 내용 | 용도 |
|---|---|---|
| `fixtures/normal_day.json` | PR 머지·리뷰, 커밋 9건, CI 전부 성공, 리뷰 대기 50시간 PR 1건 | 기본 경로 (pr_analyst만) |
| `fixtures/quiet_day.json` | 기간 내 활동 없음 | "특이사항 없음" 경로 |
| `fixtures/risky_day.json` | 52시간 리뷰 대기 PR, 6일 방치 PR, 4일 무진척 이슈, 담당자 없는 bug | 위험 판정 (pr → issue) |
| `fixtures/ci_flaky.json` | `test_refresh`가 5회 중 3회 실패, 같은 SHA에서 성공·실패, main 마지막 실패 | Handoff 경로 |
| `fixtures/monday.json` | 금~월 72시간 범위 | 기간 계산 |

- D1에 실제 팀 저장소 응답을 녹화해 만들고, 이메일 등 개인정보는 가짜 값으로 바꿔서 커밋합니다(저장소가 public이므로).
