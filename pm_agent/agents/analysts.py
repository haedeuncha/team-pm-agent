"""분석 에이전트 (PR / 이슈 / CI) 와 CI 진단 에이전트 Handoff (05) — docs/AGENTS.md 4장."""
from __future__ import annotations

from langgraph.types import Command

from ..config import Config
from ..llm import LLM, fake_finding
from ..models import (SEVERITY_ORDER, AnalysisResult, CIAnalysisResult, Diagnosis,
                      Finding, FindingDraft, RawActivity, RiskCandidate)
from ..state import PMState
from . import dumps, prompt

AREA_NAME = {"pr": "PR", "issue": "이슈", "ci": "CI"}


# ------------------------------------------------------------------ 계약 강제
def clamp_severity(proposed: str, base: str) -> str:
    """규칙이 정한 심각도에서 한 단계까지만 조정 허용."""
    b, p = SEVERITY_ORDER.index(base), SEVERITY_ORDER.index(proposed)
    return SEVERITY_ORDER[max(b - 1, min(b + 1, p))]


def enforce_contract(drafts: list[FindingDraft], cands: list[RiskCandidate], cfg: Config) -> list[Finding]:
    """후보마다 정확히 하나의 Finding. 모르는 후보는 버리고, 빠진 후보는 규칙 템플릿으로 채운다."""
    by_id = {c.id: c for c in cands}
    chosen: dict[str, FindingDraft] = {}
    for d in drafts:
        if d.candidate_id in by_id and d.candidate_id not in chosen:
            chosen[d.candidate_id] = d
    out = []
    for c in cands:
        d = chosen.get(c.id) or fake_finding(c.model_dump(), cfg.display)
        out.append(Finding(
            candidate_id=c.id, rule_id=c.rule_id, area=c.area,
            severity=clamp_severity(d.severity, c.severity),
            title=d.title[:60], explanation=d.explanation, suggested_action=d.suggested_action,
            owner=c.owner, refs=c.refs,
        ))
    return out


# ------------------------------------------------------------------ 입력 데이터
def ref_brief(raw: RawActivity, ref: str) -> dict:
    obj = raw.find(ref)
    if obj is None:
        return {"ref": ref}
    kind = ref.split(":")[0]
    if kind == "pr":
        return {"ref": ref, "title": obj.title, "author": obj.author, "draft": obj.draft,
                "created_at": obj.created_at, "updated_at": obj.updated_at,
                "requested_reviewers": obj.requested_reviewers,
                "reviews": [r.model_dump() for r in obj.reviews], "commits": len(obj.commits)}
    if kind == "issue":
        return {"ref": ref, "title": obj.title, "labels": obj.labels, "assignees": obj.assignees,
                "created_at": obj.created_at, "assigned_at": obj.assigned_at,
                "last_linked_activity": obj.last_linked_activity}
    if kind == "run":
        return {"ref": ref, "workflow": obj.workflow, "branch": obj.branch, "sha": obj.head_sha,
                "conclusion": obj.conclusion, "created_at": obj.created_at, "actor": obj.actor,
                "failed_jobs": [{"name": j.name, "failed_step": j.failed_step, "failed_tests": j.failed_tests,
                                 "log_tail": "\n".join(j.log_tail.splitlines()[-50:])} for j in obj.jobs]}
    return {"ref": ref}


def analyst_inputs(area: str, state: PMState, cfg: Config, extra: str = "") -> tuple[list[RiskCandidate], str, dict]:
    raw = state["raw"]
    cands = [c for c in state.get("candidates", []) if c.area == area]
    refs = sorted({r for c in cands for r in c.refs})
    data = [ref_brief(raw, r) for r in refs]
    names = {k: m.display for k, m in cfg.members.items()}
    user = prompt("analyst.md").format(area_name=AREA_NAME[area], extra=extra, names=dumps(names),
                                       candidates=dumps([c.model_dump() for c in cands]), data=dumps(data))
    ctx = {"candidates": [c.model_dump() for c in cands], "data": data}
    return cands, user, ctx


# ------------------------------------------------------------------ PR / 이슈
def make_analyst(area: str, llm: LLM, cfg: Config):
    node = f"{area}_analyst"

    def analyst(state: PMState) -> dict:
        cands, user, ctx = analyst_inputs(area, state, cfg)
        warnings: list[str] = []
        try:
            res = llm.structured(node, AnalysisResult, "구조화된 JSON으로만 답하라.", user, ctx)
            drafts = res.findings
        except Exception as e:  # LLM 실패 → 규칙 템플릿으로 계속 (TC-GRAPH-07)
            drafts, warnings = [], [f"{node} LLM 오류로 규칙 템플릿 사용: {type(e).__name__}"]
        return {"findings": enforce_contract(drafts, cands, cfg), "done_areas": [area],
                "warnings": warnings, "trace": [node]}

    return analyst


# ------------------------------------------------------------------ CI + Handoff
def build_handoff_payload(raw: RawActivity, cands: list[RiskCandidate]) -> dict | None:
    target = next((c for c in cands if c.rule_id == "R-CI-REPEAT"), None) or \
        next((c for c in cands if c.rule_id == "R-CI-FLAKY" and c.facts.get("tests")), None)
    if target is None:
        return None
    test = target.facts.get("test") or target.facts["tests"][0]
    flaky = any(c.rule_id == "R-CI-FLAKY" for c in cands)
    logs, commits, suspect = [], [], None
    for run in sorted((r for r in raw.ci_runs), key=lambda r: r.created_at):
        for job in run.jobs:
            if test in job.failed_tests:
                logs.append(f"--- {run.ref} ({run.branch} {run.head_sha}) ---")
                logs.extend(job.log_tail.splitlines()[-80:])
                if suspect is None:
                    c = next((c for c in raw.all_commits() if c.sha == run.head_sha), None)
                    if c:
                        suspect = c.ref
    for c in raw.all_commits():
        commits.append({"ref": c.ref, "message": c.message, "author": c.author})
    return {"test": test, "flaky": flaky, "log": "\n".join(logs),
            "commits": commits[:30], "suspect_commit": suspect,
            "outcomes": [{"ref": r.ref, "sha": r.head_sha, "conclusion": r.conclusion}
                         for r in raw.ci_runs if r.workflow == target.facts.get("workflow")]}


def make_ci_analyst(llm: LLM, cfg: Config):
    def ci_analyst(state: PMState) -> Command:
        cands, user, ctx = analyst_inputs("ci", state, cfg, extra=prompt("ci_extra.md"))
        warnings: list[str] = []
        try:
            res = llm.structured("ci_analyst", CIAnalysisResult, "구조화된 JSON으로만 답하라.", user, ctx)
            drafts, handoff = res.findings, res.handoff_to_diagnoser
        except Exception as e:
            drafts, handoff = [], False
            warnings = [f"ci_analyst LLM 오류로 규칙 템플릿 사용: {type(e).__name__}"]
        update = {"findings": enforce_contract(drafts, cands, cfg), "done_areas": ["ci"],
                  "warnings": warnings, "trace": ["ci_analyst"]}
        payload = build_handoff_payload(state["raw"], cands) if handoff else None
        if payload:   # 에이전트가 넘기기로 판단했고, 넘길 대상 테스트가 있을 때만 Handoff
            return Command(goto="ci_diagnoser", update={**update, "handoff_payload": payload})
        return Command(goto="supervisor", update=update)

    return ci_analyst


def make_ci_diagnoser(llm: LLM, cfg: Config):
    def ci_diagnoser(state: PMState) -> dict:
        payload = state["handoff_payload"]
        user = prompt("ci_diagnoser.md").format(payload=dumps(payload))
        try:
            diag = llm.structured("ci_diagnoser", Diagnosis, "구조화된 JSON으로만 답하라.", user, payload)
            return {"diagnosis": diag, "trace": ["ci_diagnoser"]}
        except Exception as e:
            return {"diagnosis": None, "trace": ["ci_diagnoser"],
                    "warnings": [f"ci_diagnoser LLM 오류로 진단 생략: {type(e).__name__}"]}

    return ci_diagnoser
