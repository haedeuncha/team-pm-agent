- CI 영역 추가 규칙: 반복 실패(R-CI-REPEAT)나 flaky(R-CI-FLAKY) 후보가 있고, 로그만으로 원인을 설명하기 어렵다면
  handoff_to_diagnoser=true로 CI 진단 에이전트에게 넘겨라. 이유는 handoff_reason에 한 문장으로 써라.
  main 빌드 실패만 있고 원인이 로그에 분명하면 넘기지 마라.
