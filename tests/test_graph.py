"""TC-GRAPH / TC-AGT: 그래프 경로와 에이전트 계약 (docs/TEST_PLAN.md 3장). LLM·네트워크 없음."""
import pytest

from pm_agent.graph import build_graph
from pm_agent.llm import FakeLLM, fake_summary
from pm_agent.models import AnalysisResult, FindingDraft, MemberSection, SummaryDraft


def run(cfg, raw, llm=None):
    llm = llm or FakeLLM(display=cfg.display)
    app = build_graph(cfg, llm, lambda: raw, log=lambda *_: None)
    return app.invoke({}, {"recursion_limit": 50})


def path(state):
    return state["trace"]


def test_graph01_quiet_day(cfg, fixture):
    s = run(cfg, fixture("quiet_day"))
    assert path(s) == ["collector", "rule_engine", "supervisor", "quiet_report"]
    assert "특이사항 없음" in s["report_md"]


def test_graph02_normal_day_pr_only(cfg, fixture):
    s = run(cfg, fixture("normal_day"))
    assert path(s) == ["collector", "rule_engine", "supervisor", "pr_analyst", "supervisor",
                       "summarizer", "validator"]


def test_graph03_risky_day_pr_then_issue(cfg, fixture):
    t = path(run(cfg, fixture("risky_day")))
    assert t.count("pr_analyst") == 1 and t.count("issue_analyst") == 1
    assert t.index("pr_analyst") < t.index("issue_analyst") < t.index("summarizer")


def test_graph04_ci_handoff_to_diagnoser(cfg, fixture):
    s = run(cfg, fixture("ci_flaky"))
    t = path(s)
    assert t[t.index("ci_analyst") + 1] == "ci_diagnoser"
    assert t[t.index("ci_diagnoser") + 1] == "supervisor"
    assert s["report"].diagnosis is not None
    assert s["report"].diagnosis.pattern == "flaky"
    assert "CI 진단" in s["report_md"]


def test_graph04b_no_handoff_when_agent_declines(cfg, fixture):
    from pm_agent.models import CIAnalysisResult
    from pm_agent.llm import fake_finding
    llm = FakeLLM(display=cfg.display, overrides={"ci_analyst": lambda ctx: CIAnalysisResult(
        findings=[fake_finding(c, cfg.display) for c in ctx["candidates"]], handoff_to_diagnoser=False)})
    assert "ci_diagnoser" not in path(run(cfg, fixture("ci_flaky"), llm))


def test_graph05_validator_fails_twice_then_fallback(cfg, fixture):
    def bad(ctx):   # 존재하지 않는 ref 로 할루시네이션
        return SummaryDraft(members=[MemberSection(member=k, yesterday=["없는 작업 [pr:999]"], today=[])
                                     for k in cfg.members], headline="x")
    s = run(cfg, fixture("normal_day"), FakeLLM(display=cfg.display, overrides={"summarizer": bad}))
    assert path(s)[-5:] == ["summarizer", "validator", "summarizer", "validator", "fallback_report"]
    assert "자동 요약 실패" in s["report_md"]
    assert "pr:999" not in s["report_md"]


def test_graph05b_validator_retry_then_success(cfg, fixture):
    calls = []

    def flaky(ctx):
        calls.append(ctx["errors"])
        if len(calls) == 1:
            return SummaryDraft(members=[], headline="x")     # 팀원 누락
        return fake_summary(ctx)
    s = run(cfg, fixture("normal_day"), FakeLLM(display=cfg.display, overrides={"summarizer": flaky}))
    assert path(s)[-4:] == ["summarizer", "validator", "summarizer", "validator"]
    assert calls[1], "재시도 프롬프트에 오류 내용이 전달돼야 함"


def test_graph06_hop_limit(cfg, fixture):
    cfg.max_hops = 1
    s = run(cfg, fixture("risky_day"))
    assert path(s).count("supervisor") == 2
    assert any("초과" in w for w in s["warnings"])


def test_graph07_llm_error_falls_back_to_rule_template(cfg, fixture):
    def boom(ctx):
        raise TimeoutError("LLM timeout")
    s = run(cfg, fixture("risky_day"), FakeLLM(display=cfg.display, overrides={"pr_analyst": boom}))
    assert len([f for f in s["report"].risks if f.area == "pr"]) == 2
    assert any("pr_analyst LLM 오류" in w for w in s["warnings"])


# ---------------------------------------------------------------- 계약
def test_agt01_one_finding_per_candidate_and_no_new_ids(cfg, fixture):
    def sloppy(ctx):   # 후보 하나 누락 + 모르는 id + 중복 + 심각도 과도 조정
        c = ctx["candidates"]
        d = lambda cid, sev="critical": FindingDraft(candidate_id=cid, severity=sev, title="t",
                                                     explanation="e", suggested_action="a")
        return AnalysisResult(findings=[d(c[0]["id"]), d(c[0]["id"]), d("c999")])
    s = run(cfg, fixture("risky_day"), FakeLLM(display=cfg.display, overrides={"pr_analyst": sloppy}))
    ids = [f.candidate_id for f in s["report"].risks]
    assert sorted(ids) == sorted(c.id for c in s["candidates"])
    stale = next(f for f in s["report"].risks if f.rule_id == "R-PR-STALE")
    assert stale.severity == "high"          # medium → critical 요청이지만 한 단계만 허용


def test_agt04_today_lines_only_from_today_evidence(cfg, fixture):
    s = run(cfg, fixture("risky_day"))
    dg = s["digests"]
    for m in s["report"].members:
        allowed = {e.ref for e in dg[m.member].today}
        for line in m.today:
            assert any(f"[{r}]" in line for r in allowed)


@pytest.mark.parametrize("name", ["normal_day", "risky_day", "ci_flaky", "quiet_day", "monday"])
def test_every_member_line_has_valid_ref(cfg, fixture, name):
    """TC-EVAL-01 의 자동 버전: 모든 줄에 유효한 근거 링크."""
    from pm_agent.models import REF_RE
    s = run(cfg, fixture(name))
    universe = s["raw"].ref_universe()
    for m in s["report"].members:
        for line in m.yesterday + m.today:
            refs = REF_RE.findall(line)
            assert refs and all(r in universe for r in refs), line
    assert "[pr:" not in s["report_md"] and "`pr:" not in s["report_md"]   # 모두 링크로 렌더링


def test_many_commit_links_are_compacted():
    """실데이터 개선: 커밋 12건이면 링크 12개가 한 줄에 몰려 읽기 어려웠음."""
    from pm_agent.render import compact_refs
    line = "커밋 5건: a, b 외 3건 [commit:a1][commit:b2][commit:c3][commit:d4][commit:e5]"
    assert compact_refs(line) == "커밋 5건: a, b 외 3건 [commit:a1][commit:b2][commit:c3] 외 2개"
    assert compact_refs("PR 머지 [pr:35]") == "PR 머지 [pr:35]"
    from pm_agent.render import space_refs
    assert space_refs("x [commit:a1][pr:2]") == "x [commit:a1] [pr:2]"
