# ✅ 내가 해야 할 일 (TODO)

> 코드는 완성됐고, 아래는 **사람이 직접 해야 하는 설정·확인 작업**입니다. 위에서부터 순서대로 진행하세요.
> 자세한 설명: [docs/OPERATIONS.md](docs/OPERATIONS.md)

## 1. GitHub에 올리기

- [ ] PC 터미널에서 push
  ```
  cd "C:\pm agent"
  git push origin main
  ```
- [ ] GitHub → **Actions** 탭에서 `ci` 워크플로가 초록색(통과)인지 확인

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
| `GH_READ_TOKEN` | 팀 저장소 **읽기 전용** Fine-grained PAT (Contents, Pull requests, Issues, Actions, Metadata: Read-only) | ✅ |
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

## 6. 첫 실행 (가상 팀으로 먼저)

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
