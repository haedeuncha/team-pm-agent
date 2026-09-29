"""LLM 추상화.

- ``FakeLLM``: 네트워크·API 키 없이 동작하는 결정론적 구현. 개발, 테스트(FakeLLM), 시연용.
- ``LangChainLLM``: OpenAI / Anthropic 등 실제 모델. ``with_structured_output`` 사용.

모든 에이전트는 ``llm.structured(node, schema, system, user, context)`` 하나만 호출한다.
실제 모델은 system/user 프롬프트를, FakeLLM 은 context(dict) 를 사용한다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Type, TypeVar

from pydantic import BaseModel

from .models import (KIND_LABEL, AnalysisResult, CIAnalysisResult, Diagnosis, FindingDraft,
                     MemberSection, SummaryDraft)

T = TypeVar("T", bound=BaseModel)


class LLM:
    def __init__(self) -> None:
        self.usage: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0})

    def structured(self, node: str, schema: Type[T], system: str, user: str, context: dict) -> T:
        raise NotImplementedError


# ---------------------------------------------------------------------------- 실제 모델
class LangChainLLM(LLM):
    def __init__(self, provider: str, model: str | None, temperature: float = 0.0):
        super().__init__()
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            self.chat = ChatOpenAI(model=model or "gpt-4o-mini", temperature=temperature, timeout=60, max_retries=2)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            self.chat = ChatAnthropic(model=model or "claude-haiku-4-5", temperature=temperature,
                                      timeout=60, max_retries=2)
        else:
            raise ValueError(f"지원하지 않는 LLM provider: {provider}")

    def structured(self, node, schema, system, user, context):
        # function_calling: 선택 필드(기본값 있는 필드)가 있는 스키마도 OpenAI/Anthropic 모두에서 안정적
        runnable = self.chat.with_structured_output(schema, include_raw=True, method="function_calling")
        out = runnable.invoke([("system", system), ("human", user)])
        meta = getattr(out.get("raw"), "usage_metadata", None) or {}
        u = self.usage[node]
        u["calls"] += 1
        u["input"] += meta.get("input_tokens", 0)
        u["output"] += meta.get("output_tokens", 0)
        if out.get("parsing_error"):
            raise out["parsing_error"]
        return out["parsed"]


# ---------------------------------------------------------------------------- FakeLLM
TITLE = {
    "R-PR-STALE": "PR #{n} 리뷰 없이 {hours:.0f}시간째 대기",
    "R-PR-ABANDONED": "PR #{n} {days:.0f}일째 활동 없음",
    "R-ISSUE-BLOCKED": "이슈 #{n} 할당 {days:.0f}일째 진척 없음",
    "R-ISSUE-UNOWNED": "버그 이슈 #{n} 담당자 없음",
    "R-CI-MAIN-RED": "{branch} 빌드 실패 ({workflow})",
    "R-CI-REPEAT": "{test} 최근 {window}회 중 {failures}회 실패",
    "R-CI-FLAKY": "같은 커밋 {sha}에서 CI 결과가 엇갈림 (flaky 의심)",
}


def _num(refs: list[str]) -> str:
    return refs[0].split(":")[1] if refs else "?"


def fake_finding(c: dict, display: Callable[[str | None], str]) -> FindingDraft:
    f, rid, n = c["facts"], c["rule_id"], _num(c["refs"])
    owner = display(c.get("owner"))
    if rid == "R-PR-STALE":
        rv = f.get("requested_reviewers") or []
        title = TITLE[rid].format(n=n, hours=f["hours_without_review"])
        if rv:
            exp = f"리뷰어({', '.join(display(r) for r in rv)})가 지정됐지만 아직 응답이 없습니다. 머지가 늦어지면 다른 작업과 충돌할 수 있습니다."
            act = f"{', '.join(display(r) for r in rv)}님이 오늘 오전 중 리뷰를 진행해 주세요."
        else:
            exp = "리뷰어가 지정되지 않아 아무도 보지 않고 있습니다."
            act = f"{owner}님이 리뷰어를 지정해 주세요."
    elif rid == "R-PR-ABANDONED":
        title = TITLE[rid].format(n=n, days=f["idle_days"])
        exp = "작업이 중단됐거나 다른 PR로 대체됐을 수 있습니다."
        act = f"{owner}님이 계속 진행할지 닫을지 결정해 주세요."
    elif rid == "R-ISSUE-BLOCKED":
        title = TITLE[rid].format(n=n, days=f["assigned_days"])
        if f.get("open_linked_prs"):
            exp = f"연결된 PR({', '.join(f['open_linked_prs'])})이 리뷰 대기 중이라 막혀 있는 것으로 보입니다."
            act = "연결된 PR 리뷰를 먼저 처리해 주세요."
        else:
            exp = "할당 후 연결된 커밋이나 PR이 없습니다. 막힌 부분이 있는지 확인이 필요합니다."
            act = f"{owner}님이 스탠드업에서 진행 상황과 막힌 점을 공유해 주세요."
    elif rid == "R-ISSUE-UNOWNED":
        title = TITLE[rid].format(n=n)
        exp = f"버그가 등록된 지 {f['age_days']:.0f}일 지났지만 담당자가 없습니다."
        act = "팀장님이 오늘 담당자를 지정해 주세요."
    elif rid == "R-CI-MAIN-RED":
        title = TITLE[rid].format(branch=f["branch"], workflow=f["workflow"])
        tests = ", ".join(f.get("failed_tests") or []) or f.get("failed_step") or "알 수 없음"
        exp = f"기본 브랜치의 마지막 CI가 실패했습니다(실패: {tests}). 이 상태에서 머지하면 문제를 찾기 어려워집니다."
        act = "새 PR 머지를 멈추고 실패 원인부터 확인해 주세요."
    elif rid == "R-CI-REPEAT":
        title = TITLE[rid].format(test=f["test"].split("::")[-1], window=f["window"], failures=f["failures"])
        exp = "같은 테스트가 반복해서 실패하고 있어 일시적인 문제가 아닐 가능성이 큽니다."
        act = "CI 진단 결과를 보고 담당자를 정해 주세요."
    elif rid == "R-CI-FLAKY":
        title = TITLE[rid].format(sha=f["sha"])
        exp = "코드가 같은데 결과가 달라서 테스트가 시간·순서·외부 환경에 의존하는 것으로 보입니다."
        act = "해당 테스트를 격리해 원인을 확인해 주세요."
    else:
        title, exp, act = rid, "", ""
    return FindingDraft(candidate_id=c["id"], severity=c["severity"], title=title,
                        explanation=exp, suggested_action=act)


LOG_HINT_RE = re.compile(r"(FAILED|Error|error|assert|Timeout|timed out|Exception|expired)")


def fake_diagnosis(ctx: dict) -> Diagnosis:
    test = ctx["test"]
    lines = [ln for ln in ctx["log"].splitlines() if LOG_HINT_RE.search(ln)][:5]
    flaky = ctx.get("flaky", False)
    joined = " ".join(lines).lower()
    if flaky and ("timeout" in joined or "timed out" in joined or "expired" in joined):
        hyp = "토큰 만료 시각을 실제 시계로 비교해서 실행 시점에 따라 결과가 달라지는 것으로 보입니다."
    elif flaky:
        hyp = "같은 코드에서 결과가 달라 실행 순서나 외부 의존성에 영향을 받는 테스트로 보입니다."
    else:
        hyp = "최근 변경 이후 계속 실패하므로 회귀(regression)일 가능성이 큽니다."
    return Diagnosis(
        test=test, pattern="flaky" if flaky else "regression", hypothesis=hyp,
        evidence_lines=lines, suspect_commit=None if flaky else ctx.get("suspect_commit"),
        next_step="시간 의존 부분을 고정(freezegun 등)하고 해당 테스트를 10회 반복 실행해 재현해 보세요."
        if flaky else "의심 커밋을 되돌린 브랜치에서 테스트를 실행해 확인해 보세요.",
    )


def fake_summary(ctx: dict) -> SummaryDraft:
    sections = []
    for dg in ctx["digests"]:
        def lines(items: list[dict]) -> list[str]:
            out, commits = [], [e for e in items if e["kind"] == "commit"]
            for e in items:
                if e["kind"] == "commit":
                    continue
                label = KIND_LABEL[e["kind"]]
                title = re.sub(r" 리뷰\((\w+)\)$", "", e["title"])
                out.append(f"{label}: {title} [{e['ref']}]")
            if commits:
                refs = "".join(f"[{e['ref']}]" for e in commits)
                head = ", ".join(e["title"] for e in commits[:2])
                more = f" 외 {len(commits) - 2}건" if len(commits) > 2 else ""
                out.append(f"커밋 {len(commits)}건: {head}{more} {refs}")
            return out
        y, t = lines(dg["yesterday"]), lines(dg["today"])
        sections.append(MemberSection(member=dg["member"], yesterday=y, today=t,
                                      note=None if (y or t) else "데이터 없음"))
    risks = ctx.get("risks") or []
    headline = (f"가장 급한 일: {risks[0]['title']}" if risks else "특별한 위험 없이 순조롭게 진행 중입니다.")[:80]
    return SummaryDraft(members=sections, headline=headline)


class FakeLLM(LLM):
    """``overrides`` 로 노드별 응답을 바꿔 끼울 수 있다 (tests 에서 사용)."""

    def __init__(self, display: Callable[[str | None], str] = lambda k: k or "미지정",
                 overrides: dict[str, Callable[[dict], Any]] | None = None):
        super().__init__()
        self.display = display
        self.overrides = overrides or {}

    def structured(self, node, schema, system, user, context):
        u = self.usage[node]
        u["calls"] += 1
        u["input"] += len(system + user) // 4   # 대략적인 토큰 추정
        if node in self.overrides:
            return self.overrides[node](context)
        if schema is Diagnosis:
            return fake_diagnosis(context)
        if schema is SummaryDraft:
            return fake_summary(context)
        drafts = [fake_finding(c, self.display) for c in context["candidates"]]
        if schema is CIAnalysisResult:
            need = any(c["rule_id"] in ("R-CI-REPEAT", "R-CI-FLAKY") for c in context["candidates"])
            return CIAnalysisResult(findings=drafts, handoff_to_diagnoser=need,
                                    handoff_reason="반복 실패/flaky 테스트 원인 진단 필요" if need else "")
        return AnalysisResult(findings=drafts)


def make_llm(provider: str, model: str | None = None, temperature: float = 0.0,
             display: Callable[[str | None], str] | None = None) -> LLM:
    if provider == "fake":
        return FakeLLM(display=display or (lambda k: k or "미지정"))
    return LangChainLLM(provider, model, temperature)
