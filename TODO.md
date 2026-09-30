# ✅ 내가 해야 할 일 (TODO)

> 코드는 완성됐고, 아래는 **사람이 직접 해야 하는 설정·확인 작업**입니다. 위에서부터 순서대로 진행하세요.
> 자세한 설명: [docs/OPERATIONS.md](docs/OPERATIONS.md)

## 1. GitHub에 올리기

- [x] PC 터미널에서 push (2026-09-29 완료)
- [x] GitHub → **Actions** 탭에서 `ci` 워크플로 통과 확인 (run #1 success)
- [ ] 이후 변경분 push: `cd "C:\pm agent"` → `git push origin main`

## 1-1. 개인 테스트 (팀 없이 먼저 해 보기, 선택)

`config.personal.yaml`은 **이 저장소(team-pm-agent) 자체**를 분석합니다. 토큰·LLM 키 없이 동작합니다.

- [x] 개인 Discord 서버를 하나 만들고 채널 웹훅 2개(본 채널, 테스트 채널) 만들기
- [x] Secrets: `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_TEST`
- [x] Variables: `PM_CONFIG` = `config.personal.yaml`
- [x] Environments: `daily-report` → Required reviewers에 **나 자신**
- [x] Run workflow (`fixture` 비우기, `since`에 `7d`, `dry_run` 체크) → 승인 → 테스트 채널 확인 (2026-09-29 #3 성공)
- [x] `dry_run` 끄고 실제 채널 발송 (2026-09-29 #4 성공, 발송 기록 저장 확인)
- [ ] 위험 요소를 보고 싶으면: 나에게 할당한 이슈 만들기, 리뷰어 없는 PR 열어 두기 등
- [ ] 팀 운영으로 넘어갈 때 `PM_CONFIG` 변수를 지우면 `config.yaml`을 사용

로컬에서 바로 확인 (토큰 없이): `python -m pm_agent.run --config config.personal.yaml --anonymous --since 7d`

## 1-2. 남은 실환경 검증 (쉬운 순서)

> 현재 상태: 개인 설정으로 실제 GitHub → 에이전트 → 승인 → Discord 발송까지 검증 완료 (2026-09-29, daily-scrum #3·#4).
> 아래는 아직 실제 환경에서 돌려 보지 않은 항목입니다. **2 → 3 → 4까지 하면 과제용 검증은 충분합니다.**

| # | 테스트 | 할 일 | 시간 | 통과 기준 |
|---|---|---|---|---|
| 1 | 정기 실행 | 없음 (평일 아침 기다리기) | — | Actions에 `schedule` 이벤트 실행이 생기고 승인 요청 메일이 옴 |
| 2 | 공휴일 건너뛰기 | 아래 명령 실행 | 1분 | "정기 실행을 건너뜁니다" 출력. 실제로는 10/9(금) 한글날 아침에 자동 확인 |
| 3 | 실제 위험 요소 | 이 저장소에 ① `bug` 라벨 이슈(담당자 없음) ② 나에게 할당한 이슈 ③ 리뷰어 없는 PR | 5분 | ①은 바로, ③은 48시간 뒤, ②는 3일 뒤 리포트에 나옴 |
| 4 | 실제 LLM | OpenAI 키 → Secret `OPENAI_API_KEY`, Variables `LLM_PROVIDER`=`openai`, `LLM_MODEL`=`gpt-4o-mini` | 10분 | `fixture`=`ci_flaky` + `dry_run`으로 실행 → "자동 요약 실패" 없음, CI 진단 나옴, 로그 끝 비용 확인 |
| 5 | Gmail | 2단계 인증 → 앱 비밀번호 → Secrets `SMTP_USERNAME`, `SMTP_PASSWORD`, `REPORT_EMAIL_TO_TEST` | 10분 | `config.personal.yaml`의 email 채널 `enabled: true` → `dry_run` 실행 → 메일 도착 |
| 6 | 팀 저장소 | 팀 합의 → `config.yaml`에 팀 저장소·팀원 아이디 → `PM_CONFIG` 변수 삭제 | 1~2일 | 팀원별 어제·오늘 할 일이 실제와 맞음 |
| 7 | 5일 운영 평가 | 매일 승인, 팀원 ❌ 반응 모으기 | 5일 | [TEST_PLAN 5장](docs/TEST_PLAN.md) 지표 |
| 8 | Slack·Teams, GitHub App, Docker | 회사 도입 시 | — | 과제에서는 "구현 완료, 실무 환경에서 검증 예정"으로 소개 |

- [ ] 1. 정기 실행 확인 (첫 예정: 2026-09-30 08:07 — 첫 회는 GitHub 쪽 지연·누락이 흔함, 다음 평일까지 확인)
- [x] 2. 공휴일 건너뛰기 (2026-09-30 로컬 확인: "회사 휴일 — 정기 실행을 건너뜁니다")
- [ ] 3. 실제 위험 요소 — 테스트 데이터 생성(2026-09-30): 이슈 #1(bug, 담당자 없음), 이슈 #2(나에게 할당), PR #3(리뷰어 없음)
  - [x] 담당자 없는 버그 → 즉시 탐지 확인 (`R-ISSUE-UNOWNED`, 실제 저장소 실행)
  - [x] 할당 이슈가 '오늘 할 일'에, 새 PR이 '어제 한 일'에 표시됨
  - [ ] 오래된 PR (48시간 뒤, 10/2 09:30 이후 확인)
  - [ ] 막힌 작업 (3일 뒤, 10/3 09:30 이후 확인)
  - [ ] 확인 끝나면 #1, #2, #3 닫기
- [ ] 4. 실제 LLM
- [ ] 5. Gmail (선택)
- [ ] 6. 팀 저장소
- [ ] 7. 5일 운영 평가

**2번 명령** (`C:\pm agent`에서)

```
python -c "import yaml,datetime;c=yaml.safe_load(open('config.personal.yaml',encoding='utf-8'));c['schedule']['extra_holidays']=[datetime.date.today().isoformat()];yaml.safe_dump(c,open('holiday_test.yaml','w',encoding='utf-8'),allow_unicode=True)"
python -m pm_agent.run --config holiday_test.yaml --anonymous --scheduled
```

`🏖️ <오늘 날짜> 회사 휴일 — 정기 실행을 건너뜁니다.`가 나오면 통과. `holiday_test.yaml`은 커밋되지 않습니다(.gitignore).

## 2. 팀 합의

- [ ] team-pm-agent 저장소에 **"PM 에이전트 도입 합의" 이슈** 열기 (본문은 채팅에서 받은 것 사용)
- [ ] 팀원 4명 동의 받기
- [ ] [docs/TEAM_AGREEMENT.md](docs/TEAM_AGREEMENT.md) 맨 위에 이슈 링크, 합의일, 팀원 아이디 채우기

## 3. `config.yaml` 실제 값으로 바꾸기

지금은 **가상 팀**(demo-team/campus-market, 해든·민수·지우·서연)으로 설정돼 있습니다.

- [ ] `team_name`: 우리 팀 이름
- [ ] `repos[0].name`: 팀 저장소 `소유자/저장소이름`
- [ ] `members`: 팀원 key, 표시 이름, **실제 GitHub 아이디** (이메일은 public 저장소라 비워 두기)
- [ ] `leader`: 승인할 팀장의 key
- [ ] `test_log_pattern`: 팀 저장소 테스트 도구 (`pytest` / `jest` / `junit`)
- [ ] 팀 저장소에 **CI(GitHub Actions)가 있는지** 확인 → 없으면 CI 분석 기능이 비어 있게 됨
- [ ] `llm.provider`, `llm.model`: 사용할 LLM (예: `openai` / `gpt-4o-mini`)
- [ ] `llm.price_per_1m_input/output`: 모델 요금 (비용 추정용, 선택)
- [ ] 알림 채널이 따로 없으면 `alerts`를 `[]`로 바꾸거나 `ALERT_WEBHOOK_URL`을 설정

## 4. Discord 웹훅 만들기

- [ ] 팀 채널: 채널 설정 → 연동 → 웹후크 → URL 복사
- [ ] 테스트용 채널을 하나 만들고 같은 방법으로 웹훅 URL 복사
- [ ] (선택) 운영 알림용 채널 웹훅

## 5. GitHub 저장소 설정 (team-pm-agent → Settings)

**Secrets and variables → Actions → Secrets**

| 이름 | 값 | 필수 |
|---|---|---|
| `GH_READ_TOKEN` | 팀 저장소 **읽기 전용** Fine-grained PAT (Contents, Pull requests, Issues, Actions, Metadata: Read-only) | ✅ (이 저장소 자신을 분석할 땐 불필요) |
| `OPENAI_API_KEY` 또는 `ANTHROPIC_API_KEY` | LLM API 키 | ✅ (fake로 운영하면 생략) |
| `DISCORD_WEBHOOK_URL` | 팀 채널 웹훅 | ✅ |
| `DISCORD_WEBHOOK_URL_TEST` | 테스트 채널 웹훅 | ✅ |
| `ALERT_WEBHOOK_URL` | 운영 알림 채널 웹훅 | 선택 |

**Secrets and variables → Actions → Variables**

| 이름 | 값 |
|---|---|
| `LLM_PROVIDER` | `openai` 또는 `anthropic` (없으면 config.yaml 값) |
| `LLM_MODEL` | 예: `gpt-4o-mini` |
| `TEAM_REPO` | (선택) config.yaml 대신 여기서 지정할 때 `소유자/저장소` |

**Environments**

- [ ] `daily-report` 만들기 → **Required reviewers**에 팀장 추가

**Actions → General**

- [ ] Workflow permissions가 막혀 있지 않은지 확인 (publish job이 `pm-agent-state` 브랜치에 기록을 씀)

## 6. 첫 실행 (가상 팀으로 먼저, 선택)

- [ ] Actions → `daily-scrum` → **Run workflow** → `fixture`에 `ci_flaky`, `dry_run` 체크
- [ ] generate job의 **Summary**에서 리포트 미리보기 확인
- [ ] 승인 → **테스트 채널**에 리포트 도착 확인

## 7. 첫 실행 (실제 팀 저장소)

- [ ] Run workflow → `fixture` 비우고, `since`에 `7d`, `dry_run` 체크
- [ ] 리포트 내용이 실제 활동과 맞는지 확인 (팀원 매핑 누락, 틀린 내용)
- [ ] 문제가 있으면 로그와 리포트를 Claude에게 전달해서 수정
- [ ] 괜찮으면 `dry_run`을 끄고 팀 채널로 한 번 발송

## 8. 운영과 평가 (평일 5일)

- [ ] 매일 아침 자동 실행 → 팀장 승인 (정오까지 승인하지 않으면 발송 안 됨)
- [ ] 팀원들이 리포트에 ✅ / ❌ 반응 남기기
- [ ] 매일 `docs/eval/YYYY-MM-DD.md`에 기록: 틀린 줄 수, 유용했던 위험 요소, 만족도(1~5)
- [ ] 비용 확인: Actions 로그 마지막의 "추정 비용"

## 9. 발표 준비

- [ ] 시연: 수동 실행 → Supervisor 라우팅 로그 → **CI 진단 Handoff**(`ci_flaky`) → 승인 → Discord 도착
- [ ] 거절(Reject)하면 발송되지 않는 장면
- [ ] 운영 5일 결과 (정확도, 만족도, 비용)
- [ ] 설계 포인트: LLM을 쓸 곳과 쓰지 않을 곳, 검증기로 할루시네이션 차단, 보안(비밀값 가림·인젝션 방어)

## 나중에 (회사 도입 시)

- [ ] [OPERATIONS.md 1장](docs/OPERATIONS.md#1-도입-전-체크리스트-회사가-결정할-것) 체크리스트: LLM 사용 승인, 법무·노무 검토
- [ ] PAT 대신 GitHub App
- [ ] Slack / Teams / 메일 채널 켜기
