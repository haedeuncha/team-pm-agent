# 팀원 연동 가이드

> 개인 테스트(`config.personal.yaml`)를 마치고 **실제 팀 저장소**로 옮길 때 운영자가 따라 하는 순서입니다.
> 팀원은 **아무것도 설치하지 않습니다.** 설정은 운영자가 이 저장소(team-pm-agent)에서 하고, 팀원은 합의하고 리포트를 받아 보기만 합니다.
> 설정 파일 예시: [`config.team.example.yaml`](../config.team.example.yaml)

---

## 1단계. 팀원 합의 (가장 먼저)

- 이 저장소에 **"PM 에이전트 도입 합의" 이슈**를 열고 팀원 전원의 동의를 받습니다. 본문과 약속 내용은 [TEAM_AGREEMENT.md](TEAM_AGREEMENT.md)를 씁니다.
- 합의가 끝나면 이슈 링크·날짜를 TEAM_AGREEMENT.md 맨 위에 채웁니다.

**팀원마다 받아 둘 정보**

| 받을 것 | 이유 | 팀원이 확인하는 법 |
|---|---|---|
| GitHub 아이디 | 커밋·PR·이슈를 팀원별로 묶기 위해 | 프로필 주소 `github.com/<아이디>` |
| 커밋 이메일이 GitHub 계정에 등록돼 있는지 | 등록 안 된 이메일로 커밋하면 "매핑되지 않은 커밋"으로 빠짐 | `git config user.email` 값이 GitHub → Settings → **Emails**에 있는지 |
| 리포트를 받을 Discord 채널 참여 | 발송 대상 | 초대 링크로 참여 |

## 2단계. 팀 저장소 읽기 권한

팀 저장소 소유 형태에 따라 방법이 다릅니다.

| 팀 저장소가… | 방법 |
|---|---|
| **public** | 추가 토큰이 필요 없을 가능성이 높습니다(공개 데이터는 기본 토큰으로 읽힘). 5단계 첫 실행에서 확인하고, 403/404가 나면 아래 방법으로 토큰을 만듭니다. |
| **Organization 소유 (private)** | Fine-grained 토큰 생성 → Resource owner: **그 조직** → Repository: 팀 저장소만 → 권한: Contents, Pull requests, Issues, Actions, Metadata 모두 **Read-only** → 조직 관리자 승인 → Secret `GH_READ_TOKEN` |
| **팀원 개인 계정 소유 (private)** | Fine-grained 토큰은 **본인 소유 저장소만** 고를 수 있어 협업자는 선택할 수 없습니다. ① 저장소 소유자가 위 권한으로 읽기 전용 토큰을 만들어 Secret에 직접 넣거나(소유자를 이 저장소 Collaborator로 초대) ② 팀 저장소를 Organization으로 옮기는 것을 권장합니다. Classic 토큰의 `repo` 권한은 범위가 너무 넓어 비권장입니다. |

회사·조직이라면 토큰 대신 **GitHub App**을 권장합니다 → [OPERATIONS.md 3장](OPERATIONS.md#3-github-인증--github-app-권장)

## 3단계. 설정 파일 만들기

1. [`config.team.example.yaml`](../config.team.example.yaml)을 참고해 **`config.yaml`** 을 실제 값으로 바꿉니다.
2. 꼭 바꿀 항목

| 항목 | 값 |
|---|---|
| `team_name` | 팀 이름 (기록 경로·메일 제목) |
| `repos[].name` | `소유자/팀저장소` (여러 개면 `alias`를 서로 다르게) |
| `members` | 팀원 전원의 key, 표시 이름, **GitHub 아이디** |
| `leader` | 승인할 사람 (members의 key) |
| `test_log_pattern` | 팀 저장소 테스트 도구: `pytest` / `jest` / `junit` |
| `ci_exclude_workflows` | 배포·알림용 등 CI 분석에서 뺄 워크플로 이름 |

> ⚠️ 이 저장소가 public이면 `members.emails`에 실제 이메일을 적지 마세요. 팀원이 GitHub에 등록된 이메일로 커밋하면 아이디만으로 매칭됩니다.

## 4단계. GitHub 설정 바꾸기 (이 저장소 → Settings)

- [ ] **Variables → `PM_CONFIG` 삭제** — 개인 설정 대신 `config.yaml`을 사용
- [ ] **승인자가 운영자가 아니면**: 그 팀원을 **Collaborators**로 초대 → **Environments → `daily-report` → Required reviewers**에 추가
- [ ] **Discord**: 팀 서버에서 "웹후크 관리" 권한이 있는 사람이 팀 채널·테스트 채널 웹훅을 만들어 Secrets `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_TEST`를 교체
- [ ] (2단계에서 토큰을 만들었다면) Secret `GH_READ_TOKEN`
- [ ] (선택) 실패 알림을 받으려면 Secret `ALERT_WEBHOOK_URL`, 아니면 `config.yaml`의 `alerts: []`

## 5단계. 첫 실행 확인

1. **Actions → daily-scrum → Run workflow**: `since`=`7d`, `fixture` 비움, **`dry_run` 체크**
2. generate job의 **Summary**(리포트 미리보기)에서 확인

| 확인 | 문제가 있으면 |
|---|---|
| 팀원 **전원** 섹션이 있는가 | `members` key·아이디 확인 |
| 하단에 "**매핑되지 않은 커밋 N건**"이 없는가 | 해당 팀원의 커밋 이메일이 GitHub에 등록돼 있는지 확인 (1단계 표) |
| 어제 한 일·오늘 할 일이 실제와 맞는가 | 틀린 줄을 캡처해 운영자에게 |
| generate가 403/404로 실패하지 않는가 | 2단계 권한 확인 |

3. 승인 → 테스트 채널 도착 확인
4. 문제없으면 `dry_run`을 끄고 한 번 실제 채널로 발송 → **다음 평일 08:07부터 자동 실행**
5. 개인 테스트용 이슈 #1, #2와 PR #3 닫기

## 팀원에게 보낼 안내 (복사해서 사용)

```
📋 이번 주부터 매일 아침 팀 채널에 데일리 스크럼 리포트가 올라옵니다.
- GitHub 커밋·PR·이슈·CI 기록을 모아 만들고, 팀장 승인 후 발송됩니다.
- 내용이 틀리면 메시지에 ❌ 반응을 남겨 주세요.
- 커밋할 때 GitHub 계정에 등록된 이메일을 써 주세요. (git config user.email 확인)
- 리포트는 평가용이 아니라 스탠드업 보조용입니다. 빼고 싶은 항목은 언제든 말해 주세요.
```

## 자주 묻는 것

| 질문 | 답 |
|---|---|
| 팀원이 설치할 게 있나요? | 없습니다. 리포트를 받아 보기만 합니다. |
| 팀 저장소에 파일이 추가되나요? | 아닙니다. 읽기만 하고, 기록은 이 저장소의 `pm-agent-state` 브랜치에만 남습니다. |
| 팀원이 늘거나 바뀌면? | `config.yaml`의 `members`만 고치면 됩니다. |
| 승인자를 바꾸려면? | `leader`와 Environment의 Required reviewers를 함께 바꿉니다. |
| 비용은? | `gpt-4o-mini` 기준 1회 약 $0.001(실측). LLM 없이(`fake`) 규칙 기반으로도 운영할 수 있습니다. |
