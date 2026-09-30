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
from ..security import UNTRUSTED_NOTE, wrap_untrusted
from ..state import PMState
from . import dumps, prompt

WEEKDAYS = "월화수목금토일"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def report_date(state: PMState, tz=KST) -> str:
    now = state["raw"].until.astimezone(tz)
    return f"{now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]})"


def sorted_risks(state: PMState):
    return sorted(state.get("findings", []), key=lambda f: -SEVERITY_ORDER.index(f.severity))


MAX_COMMITS_FOR_LLM = 8


def _render_line(line) -> str:
    return line.render() if hasattr(line, "render") else str(line)


def _to_section(m) -> MemberSection:
    return MemberSection(member=m.member, note=m.note,
                         yesterday=[_render_line(l) for l in m.yesterday],
                         today=[_render_line(l) for l in m.today])


def _llm_digest(d) -> dict:
    """LLM 에 넘길 근거: 커밋이 많으면 최근 몇 개만 (실제 LLM 실행에서 커밋 20건일 때 요약이 실패함)."""
    data = d.model_dump(mode="json")
    commits = [e for e in data["yesterday"] if e["kind"] == "commit"]
    if len(commits) > MAX_COMMITS_FOR_LLM:
        keep = {id(e) for e in commits[:MAX_COMMITS_FOR_LLM]}
        data["yesterday"] = [e for e in data["yesterday"] if e["kind"] != "commit" or id(e) in keep]
        data["omitted_commits"] = len(commits) - MAX_COMMITS_FOR_LLM
    return data


def make_summarizer(llm: LLM, cfg: Config):
    def summarizer(state: PMState) -> dict:
        attempts = state.get("attempts", 0) + 1
        risks = sorted_risks(state)
        digests = [_llm_digest(d) for d in state["digests"].values()]
        errors = state.get("validation_errors") or []
        err_txt = ("\n이전 답변의 문제(반드시 고쳐라):\n- " + "\n- ".join(errors) + "\n") if errors else ""
        risk_view = [{"title": f.title, "severity": f.severity, "refs": f.refs} for f in risks]
        user = prompt("summarizer.md").format(errors=err_txt, guard=UNTRUSTED_NOTE,
                                              digests=wrap_untrusted("EVIDENCE", dumps(digests)),
                                              risks=wrap_untrusted("RISKS", dumps(risk_view)))
        try:
            draft = llm.structured("summarizer", SummaryDraft, "구조화된 JSON으로만 답하라.", user,
                                   {"digests": digests, "risks": risk_view, "errors": errors})
        except Exception as e:
            return {"attempts": attempts, "report": None, "trace": ["summarizer"],
                    "validation_errors": [f"요약 LLM 오류: {type(e).__name__}"]}
        report = Report(
            date=report_date(state, cfg.tz), headline=draft.headline[:80], risks=risks,
            diagnosis=state.get("diagnosis"), members=[_to_section(m) for m in draft.members],
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"], cfg),
        )
        return {"attempts": attempts, "report": report, "validation_errors": [], "trace": ["summarizer"]}

    return summarizer


# ------------------------------------------------------------------ 검증기
BRACKET_RE = re.compile(r"\[([^\[\]]{1,60})\]")


def _member_key(name: str, cfg: Config) -> str:
    if name in cfg.members:
        return name
    for key, m in cfg.members.items():
        if name.strip().lower() in (m.display.lower(), m.github.lower()):
            return key
    return name


def _repair_refs(line: str, allowed: set[str]) -> str:
    """LLM 이 흔히 틀리는 근거 표기를 바로잡는다: [7d0ed54] → [commit:7d0ed54], [#3]/[PR #3] → [pr:3] 등.
    허용된 근거 안에서 하나로 정해질 때만 고친다."""
    def fix(m):
        token = m.group(1).strip()
        if REF_RE.fullmatch(f"[{token}]"):
            return m.group(0)
        t = token.lower().replace("pr ", "").replace("issue ", "").replace("run ", "").lstrip("#").strip()
        cands = [r for r in allowed if r.split(":", 1)[1].split("/")[-1] == t
                 or (r.startswith("commit:") and len(t) >= 7 and r.split("/")[-1].split(":")[-1].startswith(t[:7]))]
        return f"[{cands[0]}]" if len(cands) == 1 else m.group(0)
    return BRACKET_RE.sub(fix, line)


def _fill_text(line: str, items: dict) -> str:
    """근거만 있고 문장이 빈 줄은 근거 제목으로 문장을 채운다 ('[pr:3]' → 'PR 생성: 제목 [pr:3]')."""
    if REF_RE.sub("", line).strip():
        return line
    refs = REF_RE.findall(line)
    first = items.get(refs[0]) if refs else None
    if first is None:
        return line
    return f"{KIND_LABEL[first.kind]}: {first.title} " + "".join(f"[{r}]" for r in refs)


COMMIT_COUNT_RE = re.compile(r"커밋\s*(\d+)\s*건")


def _fix_commit_count(line: str, n: int) -> str:
    """숫자는 LLM 이 아니라 코드가 책임진다: '커밋 9건' → 실제 커밋 수 (실제 LLM 실행 #8 에서 22건을 9건으로 씀)."""
    return COMMIT_COUNT_RE.sub(f"커밋 {n}건", line) if n else line


def _normalize_section(sec: MemberSection, cfg: Config, digests) -> MemberSection:
    key = _member_key(sec.member, cfg)
    dg = digests.get(key)
    iy = {e.ref: e for e in dg.yesterday} if dg else {}
    it = {e.ref: e for e in dg.today} if dg else {}
    n_commits = sum(1 for e in iy.values() if e.kind == "commit")
    return MemberSection(member=key, note=sec.note,
                         yesterday=[_fix_commit_count(_fill_text(_repair_refs(_render_line(l), set(iy)), iy), n_commits)
                                    for l in sec.yesterday],
                         today=[_fill_text(_repair_refs(_render_line(l), set(it)), it) for l in sec.today])


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

    # V4: 모든 팀원 섹션 (표시 이름·GitHub 아이디로 쓴 경우는 key 로 바로잡은 뒤 검사)
    got = {_member_key(m.member, cfg) for m in report.members}
    missing, unknown = set(cfg.members) - got, got - set(cfg.members)
    if missing:
        errors.append(f"팀원 섹션 누락: {sorted(missing)}")
    if unknown:
        errors.append(f"알 수 없는 팀원: {sorted(unknown)} (member에는 영문 key를 써라)")

    # V2: 모든 줄에 근거 ref, ref 는 실제로 존재하고 그 팀원의 근거여야 함
    cleaned: list[MemberSection] = []
    for sec in (_normalize_section(x, cfg, digests) for x in report.members):
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
        elif report.diagnosis.suspect_commit and (
                report.diagnosis.pattern == "flaky" or report.diagnosis.suspect_commit not in raw.ref_universe()):
            # flaky 는 특정 커밋 탓이 아니고, 모르는 커밋은 지어낸 것 → 의심 커밋만 뺀다 (실제 LLM 실행에서 발견)
            report = report.model_copy(update={"diagnosis": report.diagnosis.model_copy(update={"suspect_commit": None})})

    # V6: 이메일 마스킹
    masked = EMAIL_RE.sub("[email]", report.model_dump_json())
    if masked != report.model_dump_json():
        warnings.append("리포트에서 이메일 주소를 마스킹함")
        report = Report.model_validate_json(masked)
    return report, errors, warnings


def _hybrid(report: Report, state: PMState, cfg: Config) -> tuple[Report, bool]:
    """검증을 통과한 LLM 문장은 살리고, 비어 버린 팀원만 원본 데이터 문장으로 채운다."""
    template = {m.member: m for m in _template_members(state, cfg)}
    have = {m.member: m for m in report.members}
    members, replaced = [], False
    for key in cfg.members:
        sec = have.get(key)
        dg = state["digests"].get(key)
        has_evidence = bool(dg and (dg.yesterday or dg.today))
        if sec is None or (has_evidence and not (sec.yesterday or sec.today)):
            members.append(template[key])
            replaced = replaced or has_evidence
        else:
            members.append(sec)
    return report.model_copy(update={"members": members, "risks": sorted_risks(state)}), replaced


def make_validator(cfg: Config):
    def validator(state: PMState) -> Command:
        report, errors, warnings = validate(state, cfg)
        base = {"trace": ["validator"], "warnings": warnings}
        if errors:  # 운영 중 원인 파악을 위해 로그에 남김 (실제 LLM 실행에서 필요성 확인)
            print(f"  검증 오류 {len(errors)}건 (시도 {state.get('attempts', 0)}회차):")
            for e in errors[:10]:
                print(f"   - {e[:200]}")
        if not errors:
            md = render_report(report, state["raw"], state.get("warnings", []) + warnings)
            return Command(goto="__end__", update={**base, "report": report, "report_md": md})
        if state.get("attempts", 0) < 2:
            return Command(goto="summarizer", update={**base, "validation_errors": errors})
        if report is None:          # LLM 호출 자체가 실패 → 원본 데이터 리포트
            return Command(goto="fallback_report", update={**base, "validation_errors": errors})
        report, replaced = _hybrid(report, state, cfg)
        if replaced:
            report = report.model_copy(update={"notice": "일부 팀원 요약은 자동 요약이 검증을 통과하지 못해 원본 데이터로 표시했습니다."})
        warn = warnings + [f"요약 검증 오류 {len(errors)}건 — 통과한 문장만 사용"]
        md = render_report(report, state["raw"], state.get("warnings", []) + warn)
        return Command(goto="__end__", update={**base, "warnings": warn, "report": report, "report_md": md,
                                               "validation_errors": errors})

    return validator


# ------------------------------------------------------------------ 템플릿 리포트
def _template_lines(items) -> list[str]:
    lines = [f"{KIND_LABEL[e.kind]}: {e.title} [{e.ref}]" for e in items if e.kind != "commit"]
    commits = [e for e in items if e.kind == "commit"]
    if commits:   # 커밋은 한 줄로 묶는다 (실데이터에서 커밋 20줄이 나열되던 문제)
        head = ", ".join(e.title for e in commits[:2])
        more = f" 외 {len(commits) - 2}건" if len(commits) > 2 else ""
        lines.append(f"커밋 {len(commits)}건: {head}{more} " + "".join(f"[{e.ref}]" for e in commits))
    return lines


def _template_members(state: PMState, cfg: Config) -> list[MemberSection]:
    out = []
    for key, dg in state["digests"].items():
        y = _template_lines(dg.yesterday)
        t = _template_lines(dg.today)
        out.append(MemberSection(member=key, yesterday=y, today=t, note=None if (y or t) else "데이터 없음"))
    return out


def make_fallback_report(cfg: Config):
    def fallback_report(state: PMState) -> dict:
        risks = sorted_risks(state)
        report = Report(
            date=report_date(state, cfg.tz), headline="자동 요약에 실패해 원본 데이터로 만든 리포트입니다.",
            risks=risks, diagnosis=None, members=_template_members(state, cfg),
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"], cfg),
            notice="⚠️ 자동 요약 실패, 원본 데이터 기반 리포트",
        )
        md = render_report(report, state["raw"], state.get("warnings", []))
        return {"report": report, "report_md": md, "trace": ["fallback_report"]}

    return fallback_report


def make_quiet_report(cfg: Config):
    def quiet_report(state: PMState) -> dict:
        report = Report(
            date=report_date(state, cfg.tz), headline="특이사항 없음 — 어제 팀 저장소에 새 활동이 없었습니다.",
            risks=[], members=_template_members(state, cfg),
            display_names={k: m.display for k, m in cfg.members.items()},
            stats=compute_stats(state["raw"], cfg),
        )
        md = render_report(report, state["raw"], state.get("warnings", []))
        return {"report": report, "report_md": md, "trace": ["quiet_report"]}

    return quiet_report
