# 테스트 계획서 — Team Project PM Agent

> 관련 문서: [REQUIREMENTS](REQUIREMENTS.md) · [DATA_SPEC](DATA_SPEC.md) · [AGENTS](AGENTS.md)

## 0. 구현 현황

| 파일 | 대상 | 개수 |
|---|---|---|
| `tests/test_collector.py` | TC-COL-01~09 (+ 429 대기, Jest/JUnit 패턴, 실데이터 회귀: `action_required` 등 CI 상태값) | 15 |
| `tests/test_collect_api.py` | 가짜 GitHub API로 `collect()` 전체 배선, 로그 다운로드 실패 | 2 |
| `tests/test_rules.py` | TC-RULE 전체 경계값, 임계값 설정, 근거 데이터 | 14 |
| `tests/test_graph.py` | TC-GRAPH-01~07, TC-AGT-01·04, 모든 줄 근거 링크(TC-EVAL-01 자동화), 링크 줄이기 | 17 |
| `tests/test_validator.py` | TC-AGT-02~06, V4 | 7 |
| `tests/test_edges.py` | LLM 실패, GitHub 5xx·재시도 등 오류 경로 | 14 |
| `tests/test_llm.py` | 실제 LLM 래퍼(가짜 chat 모델), FakeLLM 분기 | 7 |
| `tests/test_cli.py` | `run.py` 실행 흐름, 휴일 건너뜀, 수집 시작점, `--anonymous` | 10 |
| `tests/test_publish.py` | TC-PUB, 승인 마감, 중복 발송 방지, 이력, 채널 실패 | 11 |
| `tests/test_notify.py` | Discord·Slack·Teams·Gmail(SMTP) 형식, 테스트 대상, 비밀값 누출 방지 | 15 |
| `tests/test_security.py` | 비밀값 13종 가리기, 프롬프트 인젝션 방어 | 19 |
| `tests/test_ops.py` | 상태 저장소(local/GitHub 브랜치), 공휴일, GitHub App 토큰, 실패 알림, 설정 검증 | 13 |
| `tests/test_multirepo.py` | 여러 저장소 ref·규칙·링크·수집 | 4 |

`python -m pytest -q --cov=pm_agent` → **148 passed, 커버리지 99%** (API 키·네트워크 불필요). CI는 커버리지 95% 미만이면 실패합니다. TC-E2E-01·02는 개인 설정으로 실환경에서 통과했습니다(2026-09-29, daily-scrum #3·#4). 나머지 TC-E2E와 TC-EVAL(수동 지표)은 팀 저장소 연결 후 진행합니다.

## 1. 테스트 전략

| 단계 | 대상 | 방법 | LLM | 네트워크 | 실행 시점 |
|---|---|---|---|---|---|
| 단위 | 수집기 파싱, 규칙, 기간 계산 | pytest + fixtures | ✗ | ✗ | 모든 push |
| 계약 | Agent 출력 스키마, validator | pytest + **FakeLLM** (정해진 응답 반환) | ✗ | ✗ | 모든 push |
| 그래프 | 라우팅 경로, Handoff, 재시도 | pytest + FakeLLM + fixtures | ✗ | ✗ | 모든 push |
| E2E | Actions 전체 흐름 | `workflow_dispatch` + `dry_run` | ✓ | ✓ | 수동 |
| 품질 평가 | 실제 리포트 정확도 | 체크리스트 + 팀원 평가 | ✓ | ✓ | 운영 기간 매일 |

- 단위·계약·그래프 테스트는 team-pm-agent 저장소의 `ci.yml`에서 push마다 실행합니다. API 키 없이 돌아가야 합니다(NFR-07).
- FakeLLM은 `pm_agent/llm.py`의 `FakeLLM`에 두고 노드 이름별로 미리 정한 Pydantic 객체를 돌려줍니다.

## 2. 단위 테스트

### 2.1 수집기 (TC-COL)

| ID | 입력 | 기대 결과 |
|---|---|---|
| TC-COL-01 | 이슈 응답에 PR이 섞여 있음 | `pull_request` 키가 있는 항목 제외 |
| TC-COL-02 | `Link` 헤더에 next가 있는 3페이지 응답 | 3페이지 모두 합쳐짐 |
| TC-COL-03 | 커밋 author login 없음, 이메일은 config에 있음 | 이메일로 팀원 매핑 |
| TC-COL-04 | 봇 커밋 (`dependabot[bot]`) | 집계에서 제외 |
| TC-COL-05 | 월요일 08:07 KST, 직전 성공 실행 = 금요일 08:07 | `since` = 금요일 08:07 |
| TC-COL-06 | 직전 성공 실행 없음, 수요일 | `since` = 현재 − 24시간 |
| TC-COL-07 | pytest 로그 (ANSI 코드, 타임스탬프 포함) | `failed_tests == ["tests/test_auth.py::test_refresh"]` |
| TC-COL-08 | 커밋 메시지 "fix login (#41) refs #42" | `issue_refs == [41, 42]` |
| TC-COL-09 | PR 본문 "Closes #41, fixes #43" | `closes_issues == [41, 43]` |

### 2.2 규칙 (TC-RULE)

모든 규칙은 **경계값** 양쪽을 테스트합니다. 임계값은 `config.yaml` 기본값 기준입니다.

| 규칙 ID | 내용 | 걸리는 경우 | 걸리지 않는 경우 |
|---|---|---|---|
| R-PR-STALE | 리뷰 없이 48시간 이상 열림 | 48h 1m, 리뷰 0개 | 47h 59m / 리뷰 1개 이상 / Draft |
| R-PR-ABANDONED | 마지막 활동 후 5일 이상 | 5일 1분 | 4일 23시간 |
| R-ISSUE-BLOCKED | 할당 후 3일 이상 연결 커밋 없음 | 할당 3일, 커밋 0 | 연결 커밋 1개 이상 |
| R-ISSUE-UNOWNED | `bug` 라벨 + 담당자 없음 | bug, assignee 0 | bug 아님 / 담당자 있음 |
| R-CI-REPEAT | 같은 테스트 최근 5회 중 3회 이상 실패 | 3/5 | 2/5 |
| R-CI-FLAKY | 같은 SHA에서 성공과 실패가 모두 있음 | 같은 SHA 성공 1·실패 1 | SHA가 다름 |
| R-CI-MAIN-RED | 기본 브랜치의 마지막 CI 실패 | main 마지막 실패 | 실패 후 재실행 성공 |

- 추가로 `config.yaml`의 임계값을 바꾸면 판정이 바뀌는지 1건 확인합니다(FR-15).

### 2.3 발송 (TC-PUB)

| ID | 입력 | 기대 결과 |
|---|---|---|
| TC-PUB-01 | 4,500자 리포트 | 2000자 이하 조각 3개 이상, 섹션 중간에서 끊기지 않음 |
| TC-PUB-02 | 웹훅 429 응답 | `retry_after`만큼 기다린 뒤 재전송 |

## 3. 계약·그래프 테스트

### 3.1 Agent 계약 (TC-AGT)

| ID | 확인 내용 |
|---|---|
| TC-AGT-01 | 분석 Agent가 후보 수와 같은 수의 Finding을 반환하고, `rule_id`와 `ref`가 모두 후보 안에 있다 |
| TC-AGT-02 | FakeLLM이 없는 ref(`pr:999`)를 넣으면 validator V2가 잡아낸다 |
| TC-AGT-03 | FakeLLM이 후보 하나를 빠뜨리면 validator V3가 잡아낸다 |
| TC-AGT-04 | `today`에 할당 이슈·리뷰 요청·Draft PR 외의 항목이 들어가지 않는다 |
| TC-AGT-05 | 로그에 없는 `evidence_lines`를 가진 Diagnosis는 제외된다 (V5) |
| TC-AGT-06 | 리포트에 이메일 패턴이 있으면 마스킹된다 (V6) |

### 3.2 그래프 경로 (TC-GRAPH)

실행한 노드 순서를 기록해서 기대 경로와 비교합니다.

| ID | fixture | 기대 경로 |
|---|---|---|
| TC-GRAPH-01 | `quiet_day` | collector → rule_engine → supervisor → **quiet_report** |
| TC-GRAPH-02 | `normal_day` (PR만 변화) | … → supervisor → pr_analyst → supervisor → summarizer → validator |
| TC-GRAPH-03 | `risky_day` | supervisor가 `pr`, `issue`를 각각 한 번씩 방문 후 summarizer |
| TC-GRAPH-04 | `ci_flaky` | … → ci_analyst → **ci_diagnoser** → supervisor → … |
| TC-GRAPH-05 | FakeLLM이 validator를 2번 실패시킴 | summarizer → validator → summarizer → validator → **fallback_report** |
| TC-GRAPH-06 | supervisor가 끝나지 않도록 조작 | `hops == 6`에서 summarizer로 강제 이동 |
| TC-GRAPH-07 | LLM 예외 발생 | 해당 Agent가 후보를 설명 없는 Finding으로 변환하고 계속 진행 |

## 4. E2E 테스트 (Actions)

`workflow_dispatch` 입력의 `dry_run`(기본 true)이나 `fixture`를 주면 publish job이 Discord 대신 **테스트 채널 웹훅**(`DISCORD_WEBHOOK_URL_TEST`)으로 보냅니다.

| ID | 절차 | 기대 결과 |
|---|---|---|
| TC-E2E-01 | `since=7d`, `dry_run=true`로 수동 실행 | generate 5분 이내 성공, Job Summary에 리포트 표시 |
| TC-E2E-02 | 팀장이 Approve | 테스트 채널에 리포트 도착 |
| TC-E2E-03 | 팀장이 Reject | publish job 실행 안 됨, 채널에 메시지 없음 |
| TC-E2E-04 | `GH_READ_TOKEN`을 잘못된 값으로 설정 | generate 실패, 로그에 토큰 값이 나오지 않음 (NFR-04) |
| TC-E2E-05 | LLM API 키를 잘못된 값으로 설정 | fallback 리포트로 성공 (NFR-05) |
| TC-E2E-06 | 실행 로그 확인 | `::group::` 단위로 노드 흐름과 토큰 사용량이 보임 |

## 5. 리포트 품질 평가 (운영 기간)

실제 팀 저장소로 **평일 5일** 운영하면서 매일 기록합니다. 결과는 `docs/eval/YYYY-MM-DD.md`로 남기고 발표 자료에 씁니다.

| 지표 | 계산 방법 | 목표 |
|---|---|---|
| TC-EVAL-01 근거 유효율 | 링크가 실제 항목을 가리키는 줄 수 ÷ 전체 줄 수 | **100%** |
| TC-EVAL-02 근거 없는 항목 | 팀원이 "사실이 아니다"라고 표시한 줄 수 | **0** |
| TC-EVAL-03 위험 재현율 | 리포트에 나온 위험 ÷ 규칙이 찾은 위험 | **100%** |
| TC-EVAL-04 위험 유용성 | 팀장이 "실제로 챙겨야 했다"고 답한 위험 비율 | 70% 이상 |
| TC-EVAL-05 팀원 만족도 | "스탠드업에 도움이 됐나" 1~5점, 팀원 4명 평균 | 4.0 이상 |
| TC-EVAL-06 비용·시간 | 로그의 토큰 사용량, job 실행 시간 | NFR-01, 02 충족 |

- TC-EVAL-01, 03은 스크립트(`scripts/eval_report.py`(D7 운영 시작 때 작성 예정))로 자동 계산합니다.
- TC-EVAL-02, 04, 05는 Discord 리포트에 반응 이모지(✅ 맞음 / ❌ 틀림)를 달게 해서 모읍니다.

## 6. 일정 연결

| 단계 (PLAN 10장) | 이때 통과해야 하는 테스트 |
|---|---|
| D1 수집기 | TC-COL-01~09 |
| D2 규칙 | TC-RULE 전체 |
| D3 분석 Agent·Supervisor | TC-AGT-01, TC-GRAPH-01~03, 06, 07 |
| D4 요약·검증 | TC-AGT-02~06, TC-GRAPH-05 |
| D5 Actions·승인·발송 | TC-PUB, TC-E2E-01~06 |
| D6 Handoff | TC-GRAPH-04 |
| D7 운영 | TC-EVAL 전체 |

## 7. 완료 기준

- push마다 실행되는 테스트가 전부 통과한다.
- TC-E2E-01~05가 통과한다.
- REQUIREMENTS 6장의 인수 기준을 충족한다.
