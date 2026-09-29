# 📋 데일리 스크럼 — 2026-09-30 (수)

**가장 급한 일: main 빌드 실패 (CI)**

## 🚨 위험 요소
- 🔴 **main 빌드 실패 (CI)** · 해든 [run #144](<https://github.com/demo-team/campus-market/actions/runs/9144>)
  - 기본 브랜치의 마지막 CI가 실패했습니다(실패: tests/test_auth.py::test_refresh). 이 상태에서 머지하면 문제를 찾기 어려워집니다.
  - 👉 새 PR 머지를 멈추고 실패 원인부터 확인해 주세요.
- 🟠 **test_refresh 최근 5회 중 3회 실패** [run #141](<https://github.com/demo-team/campus-market/actions/runs/9141>) [run #142](<https://github.com/demo-team/campus-market/actions/runs/9142>) [run #144](<https://github.com/demo-team/campus-market/actions/runs/9144>)
  - 같은 테스트가 반복해서 실패하고 있어 일시적인 문제가 아닐 가능성이 큽니다.
  - 👉 CI 진단 결과를 보고 담당자를 정해 주세요.
- 🟡 **같은 커밋 d4e5f6b에서 CI 결과가 엇갈림 (flaky 의심)** [run #143](<https://github.com/demo-team/campus-market/actions/runs/9143>) [run #144](<https://github.com/demo-team/campus-market/actions/runs/9144>)
  - 코드가 같은데 결과가 달라서 테스트가 시간·순서·외부 환경에 의존하는 것으로 보입니다.
  - 👉 해당 테스트를 격리해 원인을 확인해 주세요.

## 🩺 CI 진단 — `tests/test_auth.py::test_refresh`
- 유형: **flaky**
- 가설: 토큰 만료 시각을 실제 시계로 비교해서 실행 시점에 따라 결과가 달라지는 것으로 보입니다.
- 다음 행동: 시간 의존 부분을 고정(freezegun 등)하고 해당 테스트를 10회 반복 실행해 재현해 보세요.
```
>       assert client.refresh(issued_token).status_code == 200
E       AssertionError: assert 401 == 200
tests/test_auth.py:57: AssertionError
WARNING  auth.service:service.py:88 token expired: exp=1759187231 now=1759187232
FAILED tests/test_auth.py::test_refresh - AssertionError: assert 401 == 200
```

## 👤 팀원별
### 해든
- **어제**
  - 리뷰: 채팅 알림 구독 해제 [#38](<https://github.com/demo-team/campus-market/pull/38>)
  - 커밋 1건: 토큰 갱신 로직 수정 (#41) [d4e5f6b](<https://github.com/demo-team/campus-market/commit/d4e5f6b>)
- **오늘**
  - 담당 이슈: 리프레시 토큰 갱신 버그 [#41](<https://github.com/demo-team/campus-market/issues/41>)
### 민수
- **어제**
  - 기록 없음
- **오늘**
  - 담당 이슈: 결제 취소 API [#43](<https://github.com/demo-team/campus-market/issues/43>)
### 지우
- **어제**
  - 커밋 1건: 무한 스크롤 IntersectionObserver 적용 (#42) [e5f6a7b](<https://github.com/demo-team/campus-market/commit/e5f6a7b>)
- **오늘**
  - 담당 이슈: 상품 목록 무한 스크롤 [#42](<https://github.com/demo-team/campus-market/issues/42>)
### 서연
- **어제**
  - PR 머지: 채팅 알림 구독 해제 [#38](<https://github.com/demo-team/campus-market/pull/38>)
- **오늘**
  - 담당 이슈: 채팅 읽음 표시 [#44](<https://github.com/demo-team/campus-market/issues/44>)

## 📈 요약
커밋 3 · 머지 PR 1 · 새 PR 1 · 새 이슈 0 · 닫힌 이슈 0 · CI 성공률 33%

_🤖 team-pm-agent · demo-team/campus-market · 틀린 내용은 ❌ 반응으로 알려 주세요_
