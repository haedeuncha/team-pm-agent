# Team Project PM Agent

> GitHub 저장소를 지켜보다가 **매일 아침 데일리 스크럼 리포트**를 만들어 팀 채널로 보내 주는 멀티 에이전트
> GitHub Actions + LangGraph · 팀장 승인 후 발송 · Discord / Slack / Teams / 메일

[![ci](https://github.com/haedeuncha/team-pm-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/haedeuncha/team-pm-agent/actions/workflows/ci.yml)

---

## 목차

1. [무엇을 해 주나요](#1-무엇을-해-주나요)
2. [3분 체험 (내 PC, 키 없이)](#2-3분-체험-내-pc-키-없이)
3. [우리 팀에 붙이기 (30분)](#3-우리-팀에-붙이기-30분)
4. [매일 운영하기](#4-매일-운영하기)
5. [설정 파일 (`config.yaml`)](#5-설정-파일-configyaml)
6. [명령어](#6-명령어)
7. [문제 해결](#7-문제-해결)
8. [보안·주의 사항](#8-보안주의-사항)
9. [구조와 문서](#9-구조와-문서)

---

## 1. 무엇을 해 주나요

평일 아침 08:07(KST)마다 팀 저장소를 읽고 아래 리포트를 만듭니다. **팀장이 GitHub에서 승인하면** 팀 채널로 보냅니다.

```
📋 데일리 스크럼 — 2026-09-30 (수)
가장 급한 일: main 빌드 실패 (CI)

🚨 위험 요소
- 🔴 main 빌드 실패 · 해든  [run #144]
  - 기본 브랜치의 마지막 CI가 실패했습니다(실패: tests/test_auth.py::test_refresh)
  - 👉 새 PR 머지를 멈추고 실패 원인부터 확인해 주세요.
- 🟡 PR #37 리뷰 없이 52시간째 대기 · 민수  [#37]

🩺 CI 진단 — tests/test_auth.py::test_refresh  (유형: flaky)

👤 팀원별
### 지우
- 어제: 커밋 2건 … [e5f6a7b] [5f6a7b8]
- 오늘: 담당 이슈 #42, 작업 중(Draft) #39

📈 요약: 커밋 12 · 머지 PR 1 · CI 성공률 80%
```

| 잡아내는 위험 | 기준 (설정으로 변경 가능) |
|---|---|
| 리뷰 없이 오래된 PR | 48시간 이상 |
| 방치된 PR | 마지막 활동 후 5일 이상 |
| 막힌 작업 | 할당 후 3일 이상 연결된 커밋 없음 |
| 담당자 없는 버그 | `bug` 라벨 + 담당자 없음 |
| 반복 실패 테스트 | 최근 5회 중 3회 이상 실패 |
| Flaky 테스트 | 같은 커밋에서 성공·실패가 섞임 |
| main 빌드 깨짐 | 기본 브랜치의 마지막 CI 실패 |

**믿을 수 있게 만든 장치**

- 리포트의 **모든 줄에 GitHub 링크**가 붙고, 링크가 없거나 다른 사람의 기록을 가리키면 검증기가 막습니다. LLM이 없는 일을 지어낼 수 없습니다.
- LLM이 실패하면 규칙 결과만으로 리포트를 만들어 보냅니다.
- 주말·공휴일에는 쉬고, 같은 날 두 번 보내지 않습니다.
- 로그·커밋 메시지 속 토큰·비밀번호·이메일은 LLM에 보내기 전에 가립니다.

---

## 2. 3분 체험 (내 PC, 키 없이)

필요한 것: **Python 3.10 이상**, git

```bash
git clone https://github.com/haedeuncha/team-pm-agent.git
cd team-pm-agent
pip install -r requirements.txt
```

**① 가상 팀으로 실행** (네트워크·키 불필요)

```bash
python -m pm_agent.run --fixture fixtures/ci_flaky.json
```

`report.md`가 생깁니다. 다른 상황도 볼 수 있습니다.

| fixture | 상황 | 예시 결과 |
|---|---|---|
| `normal_day` | 리뷰 대기 PR 1건 | [보기](examples/normal_day.md) |
| `risky_day` | 방치 PR, 막힌 이슈, 담당자 없는 버그 | [보기](examples/risky_day.md) |
| `ci_flaky` | CI 반복 실패 → **진단 에이전트로 Handoff** | [보기](examples/ci_flaky.md) |
| `quiet_day` | 활동 없음 → "특이사항 없음" | [보기](examples/quiet_day.md) |
| `monday` | 금~월 72시간 범위 | [보기](examples/monday.md) |

**② 공개 저장소를 실제로 읽어 보기** (토큰 없이, 시간당 60회 한도)

```bash
python -m pm_agent.run --config config.personal.yaml --anonymous --since 7d
```

`config.personal.yaml`의 `repos`와 `members`를 내 공개 저장소·내 GitHub 아이디로 바꾸면 내 기록으로 리포트가 만들어집니다.

**③ Discord로 보내 보기**

```bash
# Windows PowerShell:  $env:DISCORD_WEBHOOK_URL_TEST="https://discord.com/api/webhooks/..."
export DISCORD_WEBHOOK_URL_TEST="https://discord.com/api/webhooks/..."
python -m pm_agent.publish report.md --dry-run
```

---

## 3. 우리 팀에 붙이기 (30분)

### 3-1. 이 저장소를 내 계정·조직으로 가져오기

GitHub에서 **Fork**하거나 코드를 새 저장소에 복사합니다. 이 저장소는 **분석 대상(팀 저장소)과 별개**이며, 팀 저장소에는 아무것도 추가하지 않습니다.

> ⚠️ public 저장소로 만들 경우 `config.yaml`에 실제 이메일·웹훅 주소를 적지 마세요. 비밀값은 모두 GitHub Secrets에 넣습니다.

### 3-2. `config.yaml` 수정

```yaml
team_name: shop-team                 # 기록·메일 제목에 쓰임
repos:
  - name: acme/shop-web              # 분석할 팀 저장소 (owner/name)
    alias: ""                        # 저장소가 여러 개면 web, api 처럼 서로 다르게
leader: kim                          # 승인하는 팀장 (아래 members 의 key)
members:
  kim:  { display: 김팀장, github: kim-gh }
  lee:  { display: 이개발, github: lee-dev }
test_log_pattern: pytest             # 팀 저장소 테스트 도구: pytest | jest | junit
llm:
  provider: fake                     # 처음엔 fake(규칙 기반, 무료). 나중에 openai / anthropic
```

전체 항목은 [5장](#5-설정-파일-configyaml)을 보세요.

### 3-3. 팀 저장소 읽기 권한

둘 중 하나를 준비합니다.

| 방식 | 언제 | 만드는 법 |
|---|---|---|
| **읽기 전용 토큰 (PAT)** | 개인·소규모 팀 | GitHub → Settings → Developer settings → **Fine-grained tokens** → 저장소: 팀 저장소만 → 권한: Contents, Pull requests, Issues, Actions, Metadata 모두 **Read-only** |
| **GitHub App** | 회사·조직 (권장) | [OPERATIONS.md 3장](docs/OPERATIONS.md#3-github-인증--github-app-권장) — 퇴사·권한 변경에 영향 없음, 토큰 자동 만료 |

> 분석 대상이 **이 저장소 자신**이면(개인 테스트) 토큰 없이 Actions 기본 토큰으로 동작합니다.

### 3-4. 발송 채널 만들기 (Discord 예시)

1. Discord 채널 2개: `daily-report`(실제), `daily-report-test`(테스트)
2. 각 채널 ⚙️ → **연동** → **웹후크** → **새 웹후크** → **웹후크 URL 복사**

Slack·Teams·메일(Gmail)은 [OPERATIONS.md 4장](docs/OPERATIONS.md#4-발송-채널)을 보세요.

### 3-5. GitHub 설정 (이 저장소 → Settings)

**Secrets and variables → Actions → Secrets** (값이 암호화됨)

| 이름 | 값 | 필수 |
|---|---|---|
| `GH_READ_TOKEN` | 3-3의 토큰 (App을 쓰면 생략) | ✅ |
| `DISCORD_WEBHOOK_URL` | 실제 채널 웹훅 | ✅ |
| `DISCORD_WEBHOOK_URL_TEST` | 테스트 채널 웹훅 | ✅ |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | LLM 키 | `llm.provider`가 fake가 아닐 때 |
| `ALERT_WEBHOOK_URL` | 실패 알림 받을 채널 웹훅 | 선택 (없으면 `config.yaml`의 `alerts: []`) |

**Variables** (값이 그대로 보임)

| 이름 | 예시 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `openai` | 비우면 `config.yaml` 값 |
| `LLM_MODEL` | `gpt-4o-mini` | |
| `PM_CONFIG` | `config.yaml` | 다른 설정 파일을 쓸 때만 |
| `TEAM_REPO` | `acme/shop-web` | `config.yaml` 대신 여기서 지정할 때만 |

**Environments → New environment**

- 이름 `daily-report` → **Required reviewers**에 팀장 추가 → **Save protection rules**
- 팀장 본인이 실행한 것도 승인해야 하면 **Prevent self-review**는 끕니다.

### 3-6. 첫 실행 확인

1. **Actions → daily-scrum → Run workflow**
2. `since`: `7d`, `fixture`: 비움, **`dry_run`: 체크** → Run
3. 1분 뒤 실행 화면의 **generate summary**에서 리포트 미리보기 확인
4. **Review deployments → daily-report 체크 → Approve and deploy**
5. `daily-report-test` 채널 도착 확인 → publish summary에 `discord ✅`

문제가 없으면 끝입니다. 다음 평일 08:07부터 자동으로 동작합니다.

---

## 4. 매일 운영하기

### 팀장

1. 08:10쯤 GitHub 알림(메일)이 옵니다: "review your deployment"
2. 실행 화면에서 **generate summary**(리포트 미리보기)를 읽고
3. **Review deployments → Approve and deploy** (보내지 않으려면 **Reject**)
4. **12:00까지** 승인하지 않으면 발송되지 않습니다 (`approval_deadline`).

### 팀원

- 리포트 항목의 링크로 바로 PR·이슈·CI 로그로 이동합니다.
- 내용이 틀리면 메시지에 **❌ 반응**을 남기고 운영자에게 알려 주세요.

### 수동 실행 (Run workflow 입력값)

| 입력 | 설명 |
|---|---|
| `since` | `1d`, `7d` 등. 비우면 **마지막으로 발송된 리포트 이후** |
| `fixture` | 가상 팀으로 시연할 때 (`ci_flaky` 등). 비우면 실제 팀 저장소 |
| `dry_run` | 체크하면 **테스트 채널로만** 보내고 발송 기록을 남기지 않음 (기본 체크) |

### 자동으로 처리되는 것

| 상황 | 동작 |
|---|---|
| 주말·공휴일(대체공휴일 포함)·`extra_holidays` | 실행은 되지만 바로 건너뜀, 승인 요청 없음 |
| 월요일, 휴일 다음 날, 거절한 다음 날 | 마지막 발송 이후 활동을 모두 포함 |
| 같은 날 두 번 실행 | 두 번째는 보내지 않음 (`pm-agent-state` 브랜치에 기록) |
| LLM 오류 | 규칙 기반 문장으로 대체하고 리포트 하단에 표시 |
| 실행 실패 | `alerts` 채널로 실패 알림 |

### 잠시 멈추기

- 하루만: 그날 승인하지 않으면 됩니다.
- 계속: **Actions → daily-scrum → ⋯ → Disable workflow**

---

## 5. 설정 파일 (`config.yaml`)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `team_name` | — | 기록 경로·메일 제목에 쓰임 |
| `repos[].name / alias` | — | 분석할 저장소. 여러 개면 alias 필수 (`web#35`처럼 표시) |
| `timezone` | `Asia/Seoul` | 날짜 표시, 승인 마감, 공휴일 기준 |
| `leader` | — | 승인자 (members의 key) |
| `approval_deadline` | `"12:00"` | 이 시각 이후 승인되면 발송하지 않음 |
| `members.<key>.display / github / emails` | — | 표시 이름, GitHub 아이디, 커밋 이메일(매칭용) |
| `bots` | dependabot 등 | 집계에서 제외할 계정 |
| `test_log_pattern` | `pytest` | 실패 테스트 이름 추출 방식: `pytest` / `jest` / `junit` |
| `ci_exclude_workflows` | `[]` | CI 분석에서 뺄 워크플로 이름 (배포·알림용, 이 PM 워크플로 자신 등) |
| `thresholds.*` | 48h / 5d / 3d / 5회 중 3회 | 위험 판정 기준 (1장 표) |
| `schedule.skip_weekends / skip_holidays` | `true` | 주말·공휴일 건너뛰기 |
| `schedule.holiday_country` | `KR` | `US`, `JP` 등 |
| `schedule.extra_holidays` | `[]` | 창립기념일 등 `["2026-11-02"]` |
| `llm.provider / model` | `fake` | `fake`(무료·규칙 기반) / `openai` / `anthropic` |
| `llm.price_per_1m_input / output` | `0` | 로그에 추정 비용을 표시하려면 모델 요금(USD) 입력 |
| `channels[]` | Discord | 발송 채널 목록. `type`: `discord` / `slack` / `teams` / `email`, `enabled`로 켜고 끔 |
| `alerts[]` | Discord | 실패 알림 채널. 없으면 `[]` |
| `state.backend` | `github` | 발송 기록 저장: `github`(전용 브랜치) / `local` / `none` |
| `security.redact_secrets` | `true` | 비밀값 가리기 |
| `security.extra_patterns` | `[]` | 회사 고유 비밀 형식 (정규식) |
| `github.api_url` | — | GitHub Enterprise Server면 `https://<호스트>/api/v3` |

> 채널을 추가하면서 **새 비밀값 이름**을 쓰면 `.github/workflows/daily-scrum.yml`의 `Send` 단계 `env`에도 한 줄 추가해야 합니다. (보안상 모든 비밀값을 한꺼번에 넘기지 않습니다.)

---

## 6. 명령어

### 리포트 만들기 — `python -m pm_agent.run`

| 옵션 | 설명 |
|---|---|
| `--config <파일>` | 설정 파일 (기본 `config.yaml`) |
| `--since 1d\|7d\|12h` | 분석 기간. 없으면 마지막 발송 리포트 이후 |
| `--fixture <json>` | GitHub 대신 fixture로 실행 |
| `--llm fake\|openai\|anthropic`, `--model <이름>` | LLM 지정 |
| `--anonymous` | 토큰 없이 공개 저장소 읽기 |
| `--scheduled` | 주말·공휴일이면 건너뜀 (정기 실행용) |
| `--out <파일>` | 결과 파일 (기본 `report.md`, 메타 정보는 `report.json`) |
| `--graph` | 에이전트 그래프 구조(Mermaid) 출력 |

### 보내기 — `python -m pm_agent.publish report.md`

| 옵션 | 설명 |
|---|---|
| `--dry-run` | 채널별 테스트 대상으로만 발송, 기록 안 남김 |
| `--print` | 보내지 않고 나눈 메시지만 출력 |
| `--channel <type 또는 name>` | 특정 채널만 |
| `--force` | 이미 보낸 날짜여도 다시 발송 |

종료 코드: `0` 성공·건너뜀, `1` 일부 채널 실패, `2` 보낼 채널 없음

### 기타

```bash
python -m pm_agent.alert --stage generate      # 실패 알림 테스트
python -m pytest -q --cov=pm_agent             # 테스트 (키·네트워크 불필요)
python scripts/make_fixtures.py                # 가상 팀 fixture 다시 만들기
```

실제 LLM 사용: `pip install -r requirements-llm.txt` 후 `OPENAI_API_KEY`(또는 `ANTHROPIC_API_KEY`) 환경 변수 설정.

---

## 7. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 실행이 "Action required"로 멈추고 "may be malicious" 경고 | 워크플로가 모든 비밀값을 넘기는 형태(`toJSON(secrets)`) | 이 저장소의 워크플로를 그대로 쓰세요. 수정할 땐 비밀값을 이름으로 하나씩 넘깁니다. 경고가 뜬 실행은 **승인하지 말고** 목록의 ⋯ → Delete로 지웁니다. |
| generate 실패: `GitHub 인증 정보가 없습니다` | `GH_READ_TOKEN` 없음 | 3-3, 3-5 확인 |
| generate 실패: 404 / `Resource not accessible` | 토큰에 팀 저장소 권한 없음 | Fine-grained 토큰의 저장소 선택·권한 확인. 조직 저장소면 조직의 토큰 승인 필요 |
| publish가 "모든 채널을 건너뛰었습니다" | 채널 비밀값이 없음 | Secrets 이름이 `config.yaml`의 `*_env`와 같은지 확인 (대소문자 포함) |
| 승인했는데 "승인 마감이 지나 발송하지 않습니다" | `approval_deadline` 이후 승인 | 설정 변경 또는 다음 날 승인 |
| "이미 발송했습니다" | 같은 날짜 재실행 | 정상. 다시 보내려면 `--force` |
| 팀원 이름 대신 GitHub 아이디가 보이거나 "매핑되지 않은 커밋" | `members`에 아이디·이메일 누락 | `members.<key>.github`, `emails` 보완 |
| 리포트 상단 "일부 팀원 요약은 … 원본 데이터로 표시" | LLM 문장이 두 번 검증에 걸림 | 통과한 문장만 쓰고 나머지는 원본으로 대체된 것. Actions 로그의 "검증 오류" 확인 |
| 리포트 상단 "자동 요약 실패" | LLM 호출 자체가 실패 (키·요금·네트워크) | `OPENAI_API_KEY`, 결제 상태 확인 |
| CI 위험이 안 잡힘 | 팀 저장소에 CI가 없거나 테스트 이름 추출 실패 | CI 추가, `test_log_pattern` 확인 |
| 정기 실행이 안 옴 | 공휴일, 또는 워크플로 비활성화 | Actions 실행 기록의 "건너뜁니다" 로그 확인 |

---

## 8. 보안·주의 사항

- **도입 전 팀 합의**: 팀원 활동을 집계하는 도구입니다. [TEAM_AGREEMENT.md](docs/TEAM_AGREEMENT.md)로 수집 범위와 "평가에 쓰지 않는다"는 원칙을 먼저 합의하세요.
- **회사 도입**: 외부 LLM 사용 승인, 근로자 모니터링 관련 법무·노무 검토가 필요할 수 있습니다 → [OPERATIONS.md 1장](docs/OPERATIONS.md#1-도입-전-체크리스트-회사가-결정할-것). 승인 전에는 `llm.provider: fake`로 운영할 수 있습니다.
- 수집은 **읽기 전용**이며 팀 저장소를 수정하지 않습니다. 쓰기는 이 저장소의 `pm-agent-state` 브랜치(발송 기록)뿐입니다.
- 웹훅 URL·토큰·API 키는 **Secrets에만** 넣고, 코드·채팅·이슈에 붙여 넣지 마세요.

---

## 9. 구조와 문서

```
Actions(평일 08:07) ─ generate: 수집 → 규칙 → Supervisor → PR/이슈/CI 분석 Agent
                   │                                   └ CI 진단 Agent (Handoff)
                   │            → 요약 Agent → 검증기 → report.md (미리보기)
                   └ publish : [팀장 승인] → 마감·중복 확인 → 채널 발송 → 기록
```

```
pm_agent/        collector/ (GitHub 수집·인증) · rules.py (판정) · agents/ (Supervisor·분석·요약·검증)
                 graph.py · llm.py · notify.py (채널) · store.py (기록) · security.py · workcalendar.py
config.yaml      팀 설정            config.personal.yaml  개인 테스트용
fixtures/        가상 팀 데이터      examples/             예시 리포트
tests/           테스트 159개 (커버리지 99%)
```

| 문서 | 내용 |
|---|---|
| [TODO.md](TODO.md) | 도입 체크리스트 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 운영 가이드: GitHub App, 채널별 설정, 보안, 장애 대응 |
| [docs/PLAN.md](docs/PLAN.md) | 전체 계획·아키텍처 |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 요구사항 |
| [docs/DATA_SPEC.md](docs/DATA_SPEC.md) | 수집 데이터 명세 |
| [docs/AGENTS.md](docs/AGENTS.md) | 에이전트 설계 |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | 테스트 계획 |
| [docs/TEAM_AGREEMENT.md](docs/TEAM_AGREEMENT.md) | 팀 합의서 |

적용 과정: 09 GitHub Actions · 03 Supervisor · 05 Handoff · 06 발송 승인
