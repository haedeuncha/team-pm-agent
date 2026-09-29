# Team Project PM Agent

> Daily Scrum Automation with GitHub Actions + Multi-Agent (LangGraph)

매일 아침 GitHub Actions가 팀 저장소의 커밋·PR·이슈·CI 결과를 수집하고, 멀티 에이전트가 **팀원별 어제 한 일 / 오늘 할 일 / 위험 요소**를 정리합니다. 팀장이 승인하면 팀 채널로 데일리 리포트를 발송합니다.

```
GitHub Actions(평일 08:07 KST)
 → 수집기: 커밋·PR·이슈·CI 결과
 → Supervisor → PR / CI / 이슈 분석 Agent (→ CI 진단 Agent Handoff)
 → 요약 Agent: 팀원별 어제 / 오늘 / 위험 요소
 → 팀장 승인 (GitHub Environment) → Discord 데일리 리포트
```

## 문서
- [계획서 (PLAN.md)](docs/PLAN.md)

## 적용 과정
09 GitHub Actions · 03 Supervisor · 05 Handoff · 06 발송 승인
