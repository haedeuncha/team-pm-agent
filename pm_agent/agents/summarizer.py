"""요약 에이전트, 검증기, 템플릿 리포트 — docs/AGENTS.md 5·6장."""
from __future__ import annotations

import re
from datetime import datetime

from langgraph.types import Command

from ..collector.window import KST
from ..config import Config
from ..llm import LLM
from ..models import (KIND_LABEL, REF_RE, SEVERITY_ORDER, MemberSection, Report, SummaryDraft)
from ..render import render_report
from ..rules import compute_stats
from ..state import PMState
from . import dumps, prompt

WEEKDAYS = "월화수목금토일"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def report_date(state: PMState) -> str:
    now = state["raw"].until.astimezone(KST)
    return f"{now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]})"


def sorted_risks(state: PMState):
    return sorted(state.get("findings", []), key=lambda f: -SEVERITY_ORDER.index(f.severity))


def make_summarizer(llm: LLM, cfg: Config):
    def summarizer(state: PMState) -> dict:
        attempts = state.get("attempts", 0) + 1
        risks = sorted_risks(state)
        digests = [d.model_dump(mode="json") for d in state["digests"].values()]
        errors = state.get("validation_errors") or []
        err_txt = ("\n이전 답변의 문제(반드시 고쳐라):\n- " + "\n- ".join(errors) + "\n") if errors else ""
        risk_view = [{"title": f.title, "severity": f.severity, "refs": f.refs} for f in risks]
        user = prompt("summarizer.md").format(errors=err_txt, digests=dumps(digests), risks=dumps(risk_view))
        try:
            draft = llm.structured("summarizer", SummaryDraft, "구조화된 JSON으로만 답하라.", user,
                                   {"digests": digests, "risks": risk_view, "errors": errors})
        except Exception as e:
            return {"attempts": attempts, "report": None, "trace": ["summarizer"],
                    "validation_errors": [f"요약 LLM 오류: {type(e).__name__}"]}
        report = Report(
            date=report_date(state), headline=draft.headline[:80], risks=risks,
            diagnosis=state.get("diagnosis"), members=draft.members,
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"]),
        )
        return {"attempts": attempts, "report": report, "validation_errors": [], "trace": ["summarizer"]}

    return summarizer


# ------------------------------------------------------------------ 검증기
def validate(state: PMState, cfg: Config) -> tuple[Report | None, list[str], list[str]]:
    """(정리된 report, 재시도가 필요한 오류, 경고) 를 반환."""
    report = state.get("report")
    if report is None:
        return None, list(state.get("validation_errors") or ["요약 결과 없음"]), []
    errors, warnings = [], []
    raw, digests = state["raw"], state["digests"]
    universe = raw.ref_universe()

    # V3: 모든 후보가 risks 에 하나씩
    cand_ids = {c.id for c in state.get("candidates", [])}
    risk_ids = [f.candidate_id for f in report.risks]
    if set(risk_ids) != cand_ids or len(risk_ids) != len(set(risk_ids)):
        errors.append(f"위험 요소 누락/중복: 후보 {sorted(cand_ids)} vs 리포트 {sorted(risk_ids)}")

    # V4: 모든 팀원 섹션
    got = {m.member for m in report.members}
    missing, unknown = set(cfg.members) - got, got - set(cfg.members)
    if missing:
        errors.append(f"팀원 섹션 누락: {sorted(missing)}")
    if unknown:
        errors.append(f"알 수 없는 팀원: {sorted(unknown)} (member에는 영문 key를 써라)")

    # V2: 모든 줄에 근거 ref, ref 는 실제로 존재하고 그 팀원의 근거여야 함
    cleaned: list[MemberSection] = []
    for sec in report.members:
        dg = digests.get(sec.member)
        allowed_y = {e.ref for e in dg.yesterday} if dg else set()
        allowed_t = {e.ref for e in dg.today} if dg else set()

        def keep(lines: list[str], allowed: set[str], label: str) -> list[str]:
            ok = []
            for ln in lines:
                refs = REF_RE.findall(ln)
                bad = [r for r in refs if r not in universe or r not in allowed]
                if not refs:
                    errors.append(f"{sec.member} {label} 근거 ref 없음: {ln!r}")
                elif bad:
                    errors.append(f"{sec.member} {label} 근거에 없는 ref {bad}: {ln!r}")
                else:
                    ok.append(ln)
            return ok

        y = keep(sec.yesterday, allowed_y, "어제")
        t = keep(sec.today, allowed_t, "오늘")
        if dg and (allowed_y or allowed_t) and not (sec.yesterday or sec.today):
            errors.append(f"{sec.member} 근거가 있는데 요약이 비어 있음")
        cleaned.append(MemberSection(member=sec.member, yesterday=y, today=t,
                                     note=sec.note if (y or t) else (sec.note or "데이터 없음")))
    order = list(cfg.members)
    cleaned.sort(key=lambda s: order.index(s.member) if s.member in order else 99)
    report = report.model_copy(update={"members": cleaned})

    # V5: 진단 인용 줄은 로그에 그대로 있어야 함
    if report.diagnosis is not None:
        log_lines = set((state.get("handoff_payload") or {}).get("log", "").splitlines())
        if not report.diagnosis.evidence_lines or any(l not in log_lines for l in report.diagnosis.evidence_lines):
            warnings.append("CI 진단의 인용 줄이 로그와 달라 진단 결과를 제외함")
            report = report.model_copy(update={"diagnosis": None})

    # V6: 이메일 마스킹
    masked = EMAIL_RE.sub("[email]", report.model_dump_json())
    if masked != report.model_dump_json():
        warnings.append("리포트에서 이메일 주소를 마스킹함")
        report = Report.model_validate_json(masked)
    return report, errors, warnings


def make_validator(cfg: Config):
    def validator(state: PMState) -> Command:
        report, errors, warnings = validate(state, cfg)
        base = {"trace": ["validator"], "warnings": warnings}
        if not errors:
            md = render_report(report, state["raw"], state.get("warnings", []) + warnings)
            return Command(goto="__end__", update={**base, "report": report, "report_md": md})
        if state.get("attempts", 0) < 2:
            return Command(goto="summarizer", update={**base, "validation_errors": errors})
        return Command(goto="fallback_report", update={**base, "validation_errors": errors})

    return validator


# ------------------------------------------------------------------ 템플릿 리포트
def _template_members(state: PMState, cfg: Config) -> list[MemberSection]:
    out = []
    for key, dg in state["digests"].items():
        y = [f"{KIND_LABEL[e.kind]}: {e.title} [{e.ref}]" for e in dg.yesterday]
        t = [f"{KIND_LABEL[e.kind]}: {e.title} [{e.ref}]" for e in dg.today]
        out.append(MemberSection(member=key, yesterday=y, today=t, note=None if (y or t) else "데이터 없음"))
    return out


def make_fallback_report(cfg: Config):
    def fallback_report(state: PMState) -> dict:
        risks = sorted_risks(state)
        report = Report(
            date=report_date(state), headline="자동 요약에 실패해 원본 데이터로 만든 리포트입니다.",
            risks=risks, diagnosis=None, members=_template_members(state, cfg),
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"]),
            notice="⚠️ 자동 요약 실패, 원본 데이터 기반 리포트",
        )
        md = render_report(report, state["raw"], state.get("warnings", []))
        return {"report": report, "report_md": md, "trace": ["fallback_report"]}

    return fallback_report


def make_quiet_report(cfg: Config):
    def quiet_report(state: PMState) -> dict:
        report = Report(
            date=report_date(state), headline="특이사항 없음 — 어제 팀 저장소에 새 활동이 없었습니다.",
            risks=[], members=_template_members(state, cfg),
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"]),
        )
        md = render_report(report, state["raw"], state.get("warnings", []))
        return {"report": report, "report_md": md, "trace": ["quiet_report"]}

    return quiet_report
