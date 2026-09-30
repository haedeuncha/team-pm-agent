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
    # 두 번 실패하면 통과한 문장만 쓰고, 비어 버린 팀원은 원본 데이터로 채운다 (hybrid)
    assert path(s)[-4:] == ["summarizer", "validator", "summarizer", "validator"]
    assert "원본 데이터로 표시" in s["report_md"]
    assert "pr:999" not in s["report_md"] and "없는 작업" not in s["report_md"]
    assert all(m.yesterday or m.today or m.note for m in s["report"].members)


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


def test_hybrid_keeps_valid_llm_lines(cfg, fixture):
    """한 팀원만 틀리면 그 팀원만 원본 데이터로 대체하고 나머지 LLM 문장은 유지."""
    from pm_agent.llm import fake_summary

    def partly_bad(ctx):
        d = fake_summary(ctx)
        d.members[0].yesterday = ["지어낸 일 [pr:999]"]
        d.members[0].today = []
        return d
    s = run(cfg, fixture("normal_day"), FakeLLM(display=cfg.display, overrides={"summarizer": partly_bad}))
    good = fake_summary({"digests": [d.model_dump(mode="json") for d in s["digests"].values()], "risks": []})
    assert s["report"].members[1].yesterday == [l.render() for l in good.members[1].yesterday]  # 민수: LLM 문장 유지
    assert "지어낸 일" not in s["report_md"]


def test_ref_repair_and_member_name_mapping(cfg, fixture):
    """실제 LLM 회귀: [7d0ed54], [#35], 표시 이름(해든)으로 쓴 경우 바로잡기."""
    from pm_agent.models import MemberSection, SummaryDraft
    def sloppy(ctx):
        return SummaryDraft(headline="h", members=[
            MemberSection(member="해든", yesterday=["로그인 API 머지 [#35]", "로그 추가 [c3d4e5f]"],
                          today=["토큰 버그 [issue #41]"]),
            *[MemberSection(member=k, yesterday=[], today=[], note="데이터 없음") for k in ("minsu", "jiwoo", "seoyeon")],
        ])
    s = run(cfg, fixture("normal_day"),
            FakeLLM(display=cfg.display, overrides={"summarizer": sloppy}))
    haeden = s["report"].members[0]
    assert haeden.member == "haeden"
    assert "[pr:35]" in haeden.yesterday[0] and "[commit:c3d4e5f]" in haeden.yesterday[1]
    assert "[issue:41]" in haeden.today[0]


def test_llm_digest_limits_commits(cfg):
    from pm_agent.agents.summarizer import MAX_COMMITS_FOR_LLM, _llm_digest
    from pm_agent.models import EvidenceItem, MemberDigest
    d = MemberDigest(member="haeden", display="해든", yesterday=[
        EvidenceItem(ref=f"commit:{i:07x}", kind="commit", title=f"c{i}", url="u") for i in range(20)])
    out = _llm_digest(d)
    assert len(out["yesterday"]) == MAX_COMMITS_FOR_LLM and out["omitted_commits"] == 20 - MAX_COMMITS_FOR_LLM


def test_template_groups_commits():
    from pm_agent.agents.summarizer import _template_lines
    from pm_agent.models import EvidenceItem
    items = [EvidenceItem(ref="pr:3", kind="pr_opened", title="p", url="u")] + [
        EvidenceItem(ref=f"commit:{i:07x}", kind="commit", title=f"c{i}", url="u") for i in range(5)]
    lines = _template_lines(items)
    assert len(lines) == 2 and lines[1].startswith("커밋 5건: c0, c1 외 3건")


def test_llm_returns_bare_refs_or_structured_lines(cfg, fixture):
    """실제 LLM 회귀(#7): 문장 없이 'pr:3', 'commit:...' 처럼 근거만 보낸 경우 근거 제목으로 문장을 채운다."""
    from pm_agent.models import DraftLine, DraftMember, SummaryDraft
    def bare(ctx):
        return SummaryDraft(headline="h", members=[
            DraftMember(member="haeden", yesterday=["pr:35", DraftLine(text="", refs=["commit:c3d4e5f"])],
                        today=[DraftLine(text="토큰 버그 수정 예정", refs=["issue:41"])]),
            *[DraftMember(member=k, note="데이터 없음") for k in ("minsu", "jiwoo", "seoyeon")]])
    s = run(cfg, fixture("normal_day"), FakeLLM(display=cfg.display, overrides={"summarizer": bare}))
    h = s["report"].members[0]
    assert h.yesterday[0].startswith("PR 머지: 로그인 API 구현") and h.yesterday[0].endswith("[pr:35]")
    assert h.yesterday[1].startswith("커밋: 리프레시 토큰") and h.today == ["토큰 버그 수정 예정 [issue:41]"]


def test_draftline_parsing():
    from pm_agent.models import DraftLine
    assert DraftLine.model_validate("PR 머지 [pr:3]").refs == ["pr:3"]
    assert DraftLine.model_validate("commit:abc1234").model_dump() == {"text": "", "refs": ["commit:abc1234"]}
    assert DraftLine(text="x", refs=["[pr:1]"]).render() == "x [pr:1]"


def test_ci_exclude_workflows(cfg, fixture):
    """실데이터 회귀: 승인 거절된 PM 워크플로 실행을 'main 빌드 실패'로 잡던 오탐."""
    from pm_agent.rules import compute_stats, evaluate
    raw = fixture("ci_flaky")
    assert any(c.area == "ci" for c in evaluate(raw, cfg))
    cfg.ci_exclude_workflows = ["CI"]
    assert not any(c.area == "ci" for c in evaluate(raw, cfg))
    assert compute_stats(raw, cfg)["ci_success_rate"] == "-"


def test_commit_count_is_corrected_by_code(cfg, fixture):
    """실제 LLM 회귀(#8): 커밋 22건을 '커밋 9건'으로 쓴 문제 → 코드가 실제 수로 고친다."""
    from pm_agent.models import DraftLine, DraftMember, SummaryDraft
    def wrong_count(ctx):
        return SummaryDraft(headline="h", members=[
            DraftMember(member="jiwoo", yesterday=[DraftLine(text="커밋 9건: 상품 목록 작업", refs=["commit:d4e5f6a"])]),
            *[DraftMember(member=k, note="데이터 없음") for k in ("haeden", "minsu", "seoyeon")]])
    s = run(cfg, fixture("normal_day"), FakeLLM(display=cfg.display, overrides={"summarizer": wrong_count}))
    jiwoo = next(m for m in s["report"].members if m.member == "jiwoo")
    n = sum(1 for e in s["digests"]["jiwoo"].yesterday if e.kind == "commit")
    assert jiwoo.yesterday[0].startswith(f"커밋 {n}건") and n != 9
