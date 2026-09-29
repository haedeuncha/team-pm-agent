# 운영 가이드 — 회사 환경 도입

> 대상: 팀 PM 에이전트를 실제 회사 저장소에 붙여 운영하려는 담당자
> 관련 문서: [PLAN](PLAN.md) · [AGENTS](AGENTS.md) · [TEAM_AGREEMENT](TEAM_AGREEMENT.md)

## 1. 도입 전 체크리스트 (회사가 결정할 것)

코드로 해결할 수 없는 항목입니다. **운영을 시작하기 전에** 담당 부서와 확인하세요.

| # | 항목 | 확인할 곳 | 비고 |
|---|---|---|---|
| 1 | 외부 LLM 사용 승인 | 보안팀 | 커밋 메시지·PR 제목·CI 로그 일부가 LLM으로 전송됩니다. 사내 승인 서비스(Azure OpenAI, AWS Bedrock 등)만 허용되는지, 데이터 보관(zero retention) 조건이 필요한지 확인하세요. 승인 전에는 `llm.provider: fake`로 규칙 기반 리포트만 운영할 수 있습니다. |
| 2 | 근로자 모니터링 검토 | 법무·인사(노무) | 팀원 활동을 매일 집계하는 도구입니다. 개인정보 처리 목적·항목 고지, 필요하면 근로자 대표와 협의하세요. 리포트는 **평가에 쓰지 않는다**는 원칙을 문서로 남기세요 ([TEAM_AGREEMENT](TEAM_AGREEMENT.md)). |
| 3 | GitHub App 설치 승인 | 조직 GitHub 관리자 | 개인 토큰(PAT) 대신 App을 권장합니다 (3장). |
| 4 | 발송 채널 승인 | IT 운영 | Slack/Teams 웹훅 생성 권한, 메일 발송 계정(SMTP relay) |
| 5 | 데이터 보관 기간 | 보안팀 | 리포트 이력은 상태 브랜치에 남습니다(5장). 보관 기간을 정하고 주기적으로 정리하세요. |

## 2. 한눈에 보는 구성

```
GitHub Actions (평일 08:07, 공휴일 자동 건너뜀)
 ├─ generate job ── GitHub App 토큰 → 수집(여러 저장소) → 비밀값 가리기 → 멀티 에이전트 → 검증
 │                   └ 실패 시 운영 채널 알림
 └─ publish job ─── [팀장 승인] → 승인 마감 확인 → 중복 발송 확인 → Discord/Slack/Teams/메일
                     └ 발송 기록·이력을 pm-agent-state 브랜치에 저장, 실패 시 운영 채널 알림
```

## 3. GitHub 인증 — GitHub App (권장)

PAT는 만든 사람 계정에 묶여 있어 퇴사·권한 변경 시 멈추고, 권한 범위도 넓어지기 쉽습니다. App은 조직이 관리하고 토큰이 1시간마다 자동 만료됩니다.

1. 조직 **Settings → Developer settings → GitHub Apps → New GitHub App**
   - Webhook: 끄기
   - Repository permissions (모두 **Read-only**): Contents, Pull requests, Issues, Actions, Metadata
2. 생성 후 **Private key** 발급(.pem), **App ID** 확인
3. **Install App** → 팀 저장소만 선택해서 설치
4. team-pm-agent 저장소 설정
   - Variables: `GH_APP_ID`, `GH_APP_OWNER`(조직 이름), `GH_APP_REPOSITORIES`(예: `web,api`)
   - Secrets: `GH_APP_PRIVATE_KEY`(.pem 내용 전체)
5. 워크플로가 `actions/create-github-app-token`으로 토큰을 만들어 사용합니다. App 변수가 없으면 `GH_READ_TOKEN`(PAT)을 씁니다.

서버·Docker에서 직접 실행할 때는 `GH_APP_ID`, `GH_APP_PRIVATE_KEY`, (선택) `GH_APP_INSTALLATION_ID` 환경 변수를 주면 코드가 직접 토큰을 발급합니다 (`pm_agent/collector/auth.py`).

GitHub Enterprise Server는 `config.yaml`의 `github.api_url`에 `https://<호스트>/api/v3`를 넣으면 됩니다. Actions 안에서는 `GITHUB_API_URL`이 자동으로 설정됩니다.

## 4. 발송 채널

`config.yaml`의 `channels`에서 켜고 끕니다. 여러 채널을 동시에 켤 수 있고, 한 채널이 실패해도 나머지는 발송됩니다. 비밀값은 **이름만** 설정 파일에 적고 값은 GitHub Secrets에 넣습니다(워크플로가 `SECRETS_JSON`으로 넘겨주므로 채널을 추가해도 워크플로를 고칠 필요가 없습니다).

| 채널 | 준비 | Secrets (기본 이름) | 테스트 발송 대상 |
|---|---|---|---|
| Discord | 채널 설정 → 연동 → 웹후크 | `DISCORD_WEBHOOK_URL` | `DISCORD_WEBHOOK_URL_TEST` |
| Slack | Slack App → Incoming Webhooks | `SLACK_WEBHOOK_URL` | `SLACK_WEBHOOK_URL_TEST` |
| Teams | 채널 → 워크플로 → "웹후크 요청 수신 시 채널에 게시" | `TEAMS_WEBHOOK_URL` | `TEAMS_WEBHOOK_URL_TEST` |
| 메일 (Gmail) | 발송용 Google 계정 → 2단계 인증 → **앱 비밀번호** | `SMTP_USERNAME`, `SMTP_PASSWORD`, `REPORT_EMAIL_TO` | `REPORT_EMAIL_TO_TEST` |
| 메일 (회사) | IT가 제공한 SMTP relay 주소·계정 | 위와 같음, `smtp_host`/`smtp_port` 변경 | 위와 같음 |

- 메일은 HTML과 일반 텍스트를 함께 보냅니다. 수신자가 여러 명이면 `REPORT_EMAIL_TO`에 쉼표로 구분합니다.
- 465 포트(SSL)를 쓰는 서버면 `use_ssl: true`로 바꿉니다.
- Discord 발송은 `@everyone` 같은 멘션이 동작하지 않게 막아 두었습니다.
- 수동 실행에서 `dry_run`(기본값)을 켜면 각 채널의 **테스트 대상**으로만 보내고, 발송 기록도 남기지 않습니다.

## 5. 상태 저장소 — 중복 발송 방지와 이력

`state.backend: github`(기본)는 team-pm-agent 저장소에 `pm-agent-state` 브랜치를 만들어 JSON 파일로 기록합니다. 별도 DB가 필요 없습니다.

| 경로 | 내용 | 쓰임 |
|---|---|---|
| `sent/<team>/<날짜>.json` | 발송 시각, 성공·실패 채널, 실행 ID, 다룬 기간 | 같은 날 **재발송 방지**, 다음 수집의 **시작 시각** |
| `history/<team>/<날짜>.json` | 위험 요소 수, 통계, 실행 경로, LLM 사용량·비용 | 주간·월간 추이, 비용 점검 |

- 다음 리포트는 **마지막으로 실제 발송된 리포트가 끝난 시각부터** 수집합니다. 그래서 주말·공휴일에 건너뛴 날이나 팀장이 거절한 날의 활동도 빠지지 않습니다.
- 재발송이 필요하면 `python -m pm_agent.publish report.md --force`.
- 서버·Docker 실행은 `state.backend: local` + 볼륨 마운트(`/app/.pm-agent-state`)를 쓰세요.
- 저장소를 쓸 수 없으면 경고를 남기고 중복 방지 없이 발송합니다.

## 6. 근무일

- 정기 실행(`schedule` 이벤트)은 **주말, 한국 공휴일(대체공휴일 포함), `extra_holidays`**에 자동으로 건너뜁니다. 이날은 승인 요청도 가지 않습니다.
- 해외 팀은 `timezone`과 `schedule.holiday_country`(예: `US`, `JP`)를 바꿉니다.
- 수동 실행은 휴일이어도 동작합니다.

## 7. 여러 저장소, 여러 팀

**한 팀 · 여러 저장소**: `repos`에 저장소마다 `alias`를 붙이면 한 리포트로 합쳐집니다. 링크는 `web#35`, `api run #144`처럼 표시됩니다.

```yaml
repos:
  - name: acme/shop-web
    alias: web
  - name: acme/shop-api
    alias: api
```

**여러 팀**: 팀마다 설정 파일(`teams/backend.yaml` 등)과 워크플로 파일을 하나씩 둡니다. 워크플로를 복사해 `env.PM_CONFIG`와 `environment`(팀별 승인자)만 바꾸면 됩니다. 팀마다 승인자가 다르기 때문에 한 워크플로로 묶지 않습니다.

## 8. 보안

| 위협 | 대응 | 위치 |
|---|---|---|
| CI 로그·커밋 메시지 속 비밀값 유출 | 수집 직후와 LLM 호출 직전 **두 번** 가림: GitHub·AWS·Slack·OpenAI 키, 웹훅 URL, JWT, 개인키, `password=...`, URL 속 계정, 이메일, 주민번호, 휴대폰 번호 + 회사 고유 패턴(`security.extra_patterns`) | `pm_agent/security.py` |
| 프롬프트 인젝션 (커밋 메시지에 "이전 지시를 무시하라") | 수집 데이터를 `<data>` 경계로 감싸고 "지시가 아니다" 안내 + **검증기가 근거 없는 줄을 차단**하므로 지어낸 작업이 리포트에 실릴 수 없음 | `security.wrap_untrusted`, `agents/summarizer.validate` |
| 오류 메시지로 웹훅 URL 노출 | 채널 오류 메시지를 가린 뒤 로그에 출력 | `notify.broadcast` |
| 과도한 권한 | 수집은 읽기 전용 App 토큰, 쓰기는 publish job의 `contents: write`(자기 저장소)뿐 | 워크플로 |
| 잘못된 리포트 발송 | 팀장 승인, 승인 마감, 검증 실패 시 원본 데이터 리포트로 대체 | Environment, `publish.py` |
| 컨테이너 권한 | 비루트 사용자(uid 10001)로 실행 | `Dockerfile` |

## 9. 관측과 비용

- 실행 로그는 노드별로 접히는 그룹(`::group::`)으로 나뉘고, 마지막에 실행 경로와 LLM 사용량·**추정 비용**이 나옵니다. 요금은 `llm.price_per_1m_input/output`에 모델 요금을 넣으면 계산됩니다.
- LangSmith로 LLM 호출을 추적하려면 Secret `LANGSMITH_API_KEY`와 Variable `LANGSMITH_TRACING=true`를 설정합니다(LangChain이 자동으로 보냅니다).
- 발송 결과는 publish job의 Job Summary에 채널별 표로 남습니다.

## 10. 장애 대응 (Runbook)

| 증상 | 확인 | 조치 |
|---|---|---|
| 운영 채널에 "generate 실패" 알림 | Actions 로그의 실패 노드 | 토큰 만료·권한 → App 설치 범위 확인. LLM 오류는 자동으로 규칙 템플릿으로 대체되므로 대개 수집 단계 문제입니다. 고친 뒤 Run workflow(`dry_run` 끄기). |
| 리포트가 오지 않음, 알림도 없음 | 그날 실행이 "건너뜀"인지 | 공휴일·주말이면 정상. 승인 대기 중이면 팀장에게 요청. 마감이 지났으면 로그에 "승인 마감". |
| 같은 리포트가 두 번 옴 | `pm-agent-state` 브랜치의 `sent/` | `state.backend`가 `none`인지 확인 |
| 일부 채널만 실패 | publish Job Summary 표 | 해당 채널 웹훅·비밀번호 재발급. 나머지 채널은 이미 발송됨. 다시 보내려면 `--channel <이름> --force`. |
| 리포트 내용이 틀림 | 팀원 ❌ 반응, `history/` 기록 | 규칙 임계값(`thresholds`) 조정, 팀원 매핑(`members.emails`) 보완 |
| 리포트 상단에 "자동 요약 실패" | 로그의 validator 오류 | LLM이 근거 없는 줄을 두 번 만들었다는 뜻. 모델 변경 또는 프롬프트 점검 |

## 11. 서버·Docker 실행

```bash
docker build -t team-pm-agent .
docker run --rm --env-file .env -v $PWD/state:/app/.pm-agent-state team-pm-agent pm_agent.run --scheduled
docker run --rm --env-file .env -v $PWD/state:/app/.pm-agent-state team-pm-agent pm_agent.publish report.md
```

- `.env.example`을 복사해서 값을 채웁니다. `.env`는 커밋하지 마세요.
- 승인 단계는 GitHub Actions의 Environment 기능이라 서버 실행에는 없습니다. 서버에서 운영할 경우 publish를 누가 언제 실행할지 규칙을 정하세요.

## 12. 아직 검증하지 않은 것

- 실제 GitHub API·실제 LLM·실제 채널(Discord/Slack/Teams/Gmail) 발송은 테스트에서 가짜 응답으로만 확인했습니다. 첫 운영 전 `dry_run`으로 각 채널을 한 번씩 확인하세요.
- Docker 이미지는 빌드해 보지 않았습니다.
