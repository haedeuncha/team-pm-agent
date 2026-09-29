"""StateGraph 조립 — docs/AGENTS.md 1장."""
from __future__ import annotations

import os
import time
from typing import Callable

from langgraph.graph import END, START, StateGraph

from .agents.analysts import make_analyst, make_ci_analyst, make_ci_diagnoser
from .agents.summarizer import (make_fallback_report, make_quiet_report,
                                make_summarizer, make_validator)
from .agents.supervisor import make_supervisor
from .config import Config
from .llm import LLM
from .models import RawActivity
from .rules import activity_areas, build_digests, evaluate
from .state import PMState


def _logged(name: str, fn: Callable, log: Callable[[str], None]) -> Callable:
    """Actions 로그에서 노드별로 접었다 펼 수 있도록 ::group:: 으로 감싼다 (AGENTS 8장)."""
    in_actions = os.getenv("GITHUB_ACTIONS") == "true"

    def wrapper(state):
        t0 = time.perf_counter()
        log(f"::group::[{name}]" if in_actions else f"▶ [{name}]")
        out = fn(state)
        goto = getattr(out, "goto", None)
        dt = time.perf_counter() - t0
        log(f"  → {goto if goto else 'next'} ({dt:.2f}s)")
        if in_actions:
            log("::endgroup::")
        return out
    return wrapper


def build_graph(cfg: Config, llm: LLM, source: Callable[[], RawActivity],
                log: Callable[[str], None] = print):
    def collector(state: PMState) -> dict:
        raw = source()
        return {"raw": raw, "trace": ["collector"]}

    def rule_engine(state: PMState) -> dict:
        raw = state["raw"]
        cands = evaluate(raw, cfg)
        log(f"  위험 후보 {len(cands)}건: " + ", ".join(f"{c.id}:{c.rule_id}" for c in cands))
        return {"candidates": cands, "digests": build_digests(raw, cfg),
                "active_areas": sorted(activity_areas(raw)), "hops": 0, "attempts": 0,
                "trace": ["rule_engine"]}

    g = StateGraph(PMState)
    nodes = {
        "collector": collector,
        "rule_engine": rule_engine,
        "supervisor": make_supervisor(cfg),
        "pr_analyst": make_analyst("pr", llm, cfg),
        "issue_analyst": make_analyst("issue", llm, cfg),
        "ci_analyst": make_ci_analyst(llm, cfg),
        "ci_diagnoser": make_ci_diagnoser(llm, cfg),
        "summarizer": make_summarizer(llm, cfg),
        "validator": make_validator(cfg),
        "fallback_report": make_fallback_report(cfg),
        "quiet_report": make_quiet_report(cfg),
    }
    destinations = {
        "supervisor": ("pr_analyst", "issue_analyst", "ci_analyst", "summarizer", "quiet_report"),
        "ci_analyst": ("ci_diagnoser", "supervisor"),
        "validator": ("summarizer", "fallback_report", END),
    }
    for name, fn in nodes.items():
        if name in destinations:
            g.add_node(name, _logged(name, fn, log), destinations=destinations[name])
        else:
            g.add_node(name, _logged(name, fn, log))

    g.add_edge(START, "collector")
    g.add_edge("collector", "rule_engine")
    g.add_edge("rule_engine", "supervisor")
    g.add_edge("pr_analyst", "supervisor")
    g.add_edge("issue_analyst", "supervisor")
    g.add_edge("ci_diagnoser", "supervisor")
    g.add_edge("summarizer", "validator")
    g.add_edge("fallback_report", END)
    g.add_edge("quiet_report", END)
    return g.compile()
