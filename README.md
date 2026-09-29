# Team Project PM Agent

> Daily Scrum Automation with GitHub Actions + Multi-Agent (LangGraph)

> 📌 **설정·운영에서 사람이 해야 할 일은 [TODO.md](TODO.md)에 정리돼 있습니다.**

매일 아침 GitHub Actions가 팀 저장소의 커밋·PR·이슈·CI 결과를 수집하고, 멀티 에이전트가 **팀원별 어제 한 일 / 오늘 할 일 / 위험 요소**를 정리합니다. 팀장이 승인하면 팀 채널로 데일리 리포트를 발송합니다.

```
GitHub Actions(평일 08:07 KST)
 → 수집기(코드): 커밋·PR·이슈·CI 결과
 → 규칙 엔진(코드): 위험 후보 + 팀원별 근거
 → Supervisor → PR / CI / 이슈 분석 Agent (→ CI 진단 Agent로 Handoff)
 → 요약 Agent → 검증기(근거 링크·누락 검사)
 → 팀장 승인 (GitHub Environment) → Discord 데일리 리포트
```

## 바로 실행해 보기 (API 키 없이, 가상 팀)

```bash
pip install -r requirements.txt
python -m pm_agent.run --fixture fixtures/ci_flaky.json     # → report.md
python -m pytest -q --cov=pm_agent                          # 145 passed, 커버리지 99%
```

가상 팀 **campus-market**: 해든(팀장·인증) · 민수(결제) · 지우(프론트) · 서연(채팅·알림)

| fixture | 실행 경로 | 예시 출력 |
|---|---|---|
| `normal_day` | supervisor → pr_analyst → summarizer → validator | [examples/normal_day.md](examples/normal_day.md) |
| `risky_day` | pr_analyst → issue_analyst → summarizer | [examples/risky_day.md](examples/risky_day.md) |
| `ci_flaky` | ci_analyst → **ci_diagnoser (Handoff)** → summarizer | [examples/ci_flaky.md](examples/ci_flaky.md) |
| `quiet_day` | supervisor → quiet_report | [examples/quiet_day.md](examples/quiet_day.md) |
| `monday` | 금~월 72시간 범위 | [examples/monday.md](examples/monday.md) |

실제 LLM으로 실행: `pip install -r requirements-llm.txt` 후 `--llm openai --model gpt-4o-mini` (환경 변수 `OPENAI_API_KEY`) 또는 `--llm anthropic`.
그래프 구조 보기: `python -m pm_agent.run --graph --fixture fixtures/quiet_day.json`

## 실제 팀 저장소에 연결하기

1. `config.yaml`의 `repos`, `members`(GitHub 아이디), `leader`, `test_log_pattern`, `channels`를 실제 값으로 바꿉니다. 실제 이메일·웹훅 주소는 커밋하지 말고 `*_env`(비밀값 이름)를 쓰세요.
2. 인증: **GitHub App**(회사 권장) 또는 읽기 전용 PAT(`GH_READ_TOKEN`) — [OPERATIONS 3장](docs/OPERATIONS.md#3-github-인증--github-app-권장)
3. **Settings → Secrets and variables → Actions**에 LLM 키와 채널 비밀값을 넣습니다 — [OPERATIONS 4장](docs/OPERATIONS.md#4-발송-채널)
4. **Settings → Environments → `daily-report`** 생성 → Required reviewers에 팀장 추가
5. Actions → `daily-scrum` → Run workflow (`dry_run` 체크) → 승인 → 테스트 채널 확인

로컬에서 실제 저장소 수집: `GH_READ_TOKEN=... python -m pm_agent.run --since 1d`
발송 미리보기: `python -m pm_agent.publish report.md --print`

## 실무 운영 기능

| 기능 | 내용 |
|---|---|
| 인증 | GitHub App 설치 토큰(자동 만료, 조직 관리) 또는 PAT, GitHub Enterprise Server 지원 |
| 발송 채널 | Discord · Slack · Microsoft Teams · 메일(Gmail/회사 SMTP), 동시 발송, 채널별 실패 격리 |
| 보안 | 로그·커밋 메시지의 토큰·비밀번호·이메일·주민번호 등 자동 가림(2중), 프롬프트 인젝션 완화 |
| 근무일 | 주말·한국 공휴일(대체공휴일 포함)·회사 휴일 자동 건너뜀 |
| 중복·누락 방지 | 같은 날 재발송 방지, 마지막 발송 리포트 이후부터 수집(휴일·거절한 날 활동 포함) |
| 이력 | 날짜별 리포트 통계·LLM 비용을 `pm-agent-state` 브랜치에 기록 |
| 알림 | generate/publish 실패 시 운영 채널로 알림 |
| 확장 | 한 팀 여러 저장소(`web#35`, `api#12`), 팀별 설정 파일·워크플로 |
| 배포 | GitHub Actions 또는 Docker(비루트) |

자세한 내용: [운영 가이드 (OPERATIONS.md)](docs/OPERATIONS.md)

## 문서

| 문서 | 내용 |
|---|---|
| [PLAN](docs/PLAN.md) | 전체 계획서 (아키텍처, 일정, 리스크) |
| [REQUIREMENTS](docs/REQUIREMENTS.md) | 요구사항 정의서 (사용자 스토리, FR/NFR, 인수 기준) |
| [DATA_SPEC](docs/DATA_SPEC.md) | 데이터 명세서 (GitHub API, 데이터 모델, fixtures) |
| [AGENTS](docs/AGENTS.md) | 에이전트 설계서 (그래프, 입출력 계약, 프롬프트, 검증) |
| [TEST_PLAN](docs/TEST_PLAN.md) | 테스트 계획서 (단위·그래프·E2E, 품질 평가) |
| [TEAM_AGREEMENT](docs/TEAM_AGREEMENT.md) | 팀 합의서 (수집 범위, 약속) |
| [OPERATIONS](docs/OPERATIONS.md) | 운영 가이드 (도입 체크리스트, 인증, 채널, 보안, 장애 대응) |

## 적용 과정
09 GitHub Actions · 03 Supervisor · 05 Handoff · 06 발송 승인
