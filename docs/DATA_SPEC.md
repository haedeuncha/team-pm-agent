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
| A10 | job 로그 | `GET /repos/{o}/{r}/actions/jobs/{id}/logs` | — | 실패한 job만, 302 리다이렉트를 따라감. **마지막 200줄만 저장** |

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
    conclusion: Literal["success", "failure", "cancelled", "skipped", "timed_out"] | None
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
    ci_runs: list[CIRun]                    # 기간 내 + 최근 20회
```

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

```yaml
team_repo: owner/team-repo
timezone: Asia/Seoul
leader: haedeuncha
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

`ref` 형식은 모든 문서와 코드에서 이 규칙으로 통일합니다. 검증기(AGENTS 6장)는 `ref`가 `RawActivity` 안에 실제로 있는지 확인합니다.

## 7. Fixtures

| 파일 | 내용 | 용도 |
|---|---|---|
| `fixtures/normal_day.json` | 평범한 하루 (커밋 10, PR 2, CI 전부 성공) | 기본 경로 |
| `fixtures/quiet_day.json` | 활동 없음 | "특이사항 없음" 경로 |
| `fixtures/risky_day.json` | 52시간 방치 PR, 3일 무진척 이슈, 담당자 없는 bug | 위험 판정 |
| `fixtures/ci_flaky.json` | 같은 SHA에서 성공·실패, 같은 테스트 5회 중 3회 실패 | Handoff 경로 |
| `fixtures/monday.json` | 금~월 72시간 범위 | 기간 계산 |

- D1에 실제 팀 저장소 응답을 녹화해 만들고, 이메일 등 개인정보는 가짜 값으로 바꿔서 커밋합니다(저장소가 public이므로).
