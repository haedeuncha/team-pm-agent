"""Supervisor (03). 규칙 기반 라우터 — docs/AGENTS.md 3장.

LLM 을 쓰지 않는 이유: '어느 영역을 분석할지'는 데이터(위험 후보가 있는 영역)로 명확히 정해지므로,
규칙으로 처리하면 비용 없이 항상 같은 결과가 나온다. 판단이 필요한 일은 워커 에이전트가 맡는다.
"""
from __future__ import annotations

from langgraph.types import Command

from ..config import Config
from ..state import PMState

PRIORITY = ["ci", "pr", "issue"]   # main 빌드 실패가 가장 급하므로 CI 먼저


def make_supervisor(cfg: Config):
    def supervisor(state: PMState) -> Command:
        hops = state.get("hops", 0) + 1
        base = {"hops": hops, "trace": ["supervisor"]}
        if hops > cfg.max_hops:
            return Command(goto="summarizer",
                           update={**base, "warnings": [f"supervisor 방문 {cfg.max_hops}회 초과로 요약 단계로 이동"]})
        candidates = state.get("candidates", [])
        if not candidates and not state.get("active_areas"):
            return Command(goto="quiet_report", update=base)
        todo = {c.area for c in candidates}
        remaining = [a for a in PRIORITY if a in todo and a not in state.get("done_areas", [])]
        if not remaining:
            return Command(goto="summarizer", update=base)
        return Command(goto=f"{remaining[0]}_analyst", update=base)

    return supervisor
