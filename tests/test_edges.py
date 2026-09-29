"""오류·경계 경로: LLM 실패, GitHub 5xx, 참조 조회 등."""
import httpx
import pytest

from conftest import NOW
from pm_agent.agents.analysts import build_handoff_payload, ref_brief
from pm_agent.agents.summarizer import validate
from pm_agent.collector import logparse
from pm_agent.collector.github import GitHubClient, fetch_last_success
from pm_agent.graph import build_graph
from pm_agent.llm import FakeLLM
from pm_agent.models import Issue, MemberSection
from pm_agent.rules import evaluate


def boom(ctx):
    raise TimeoutError("llm down")


def run(cfg, raw, **overrides):
    app = build_graph(cfg, FakeLLM(display=cfg.display, overrides=overrides), lambda: raw, log=lambda *_: None)
    return app.invoke({}, {"recursion_limit": 50})


def test_ci_analyst_llm_error_no_handoff(cfg, fixture):
    s = run(cfg, fixture("ci_flaky"), ci_analyst=boom)
    assert "ci_diagnoser" not in s["trace"] and len(s["report"].risks) == 3
    assert any("ci_analyst LLM 오류" in w for w in s["warnings"])


def test_ci_diagnoser_llm_error_skips_diagnosis(cfg, fixture):
    s = run(cfg, fixture("ci_flaky"), ci_diagnoser=boom)
    assert s["report"].diagnosis is None
    assert any("ci_diagnoser" in w for w in s["warnings"])


def test_summarizer_llm_error_goes_to_fallback(cfg, fixture):
    s = run(cfg, fixture("normal_day"), summarizer=boom)
    assert s["trace"][-1] == "fallback_report"
    assert any("요약 LLM 오류" in e for e in s["validation_errors"])


def test_graph_logs_groups_in_actions(cfg, fixture, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    lines = []
    build_graph(cfg, FakeLLM(), lambda: fixture("quiet_day"), log=lines.append).invoke({})
    assert "::group::[supervisor]" in lines and "::endgroup::" in lines


def test_validator_unknown_member_and_empty_section(cfg, fixture):
    s = run(cfg, fixture("normal_day"))
    rep = s["report"]
    members = [m.model_copy(update={"yesterday": [], "today": []}) if m.member == "haeden" else m for m in rep.members]
    members.append(MemberSection(member="ghost", yesterday=[], today=[]))
    _, errors, _ = validate({**s, "report": rep.model_copy(update={"members": members})}, cfg)
    assert any("알 수 없는 팀원" in e for e in errors)
    assert any("haeden 근거가 있는데" in e for e in errors)


def test_ref_brief_and_find_unknown(fixture):
    raw = fixture("ci_flaky")
    assert ref_brief(raw, "commit:d4e5f6b") == {"ref": "commit:d4e5f6b"}
    assert ref_brief(raw, "pr:999") == {"ref": "pr:999"}
    assert raw.find("wiki:1") is None


def test_handoff_payload_none_without_target(cfg, fixture):
    raw = fixture("ci_flaky")
    main_red = [c for c in evaluate(raw, cfg) if c.rule_id == "R-CI-MAIN-RED"]
    assert build_handoff_payload(raw, main_red) is None


def test_issue_assigned_to_two_members_reported_once(cfg, empty_raw):
    from datetime import timedelta
    i = Issue(number=7, title="공동 작업", state="open", assignees=["jiwoo", "minsu"],
              created_at=NOW - timedelta(days=9), assigned_at=NOW - timedelta(days=5), url="u")
    empty_raw.open_assigned = {"jiwoo": [i], "minsu": [i]}
    assert [c.rule_id for c in evaluate(empty_raw, cfg)] == ["R-ISSUE-BLOCKED"]


def test_config_lookup_none(cfg):
    assert cfg.member_by_login(None) is None and cfg.member_by_email(None) is None
    assert cfg.display(None) == "미지정"


def test_logparse_unknown_pattern():
    with pytest.raises(ValueError):
        logparse.failed_tests("x", "nunit")


def test_since_format_error():
    from pm_agent.collector.window import parse_since
    with pytest.raises(ValueError):
        parse_since("1주")


def test_github_retries_5xx_then_succeeds():
    seq, waits = [500, 502, 200], []
    transport = httpx.MockTransport(lambda req: httpx.Response(seq.pop(0), json={"ok": 1}))
    assert GitHubClient("t", transport=transport, sleep=waits.append).get("/x") == {"ok": 1}
    assert waits == [1, 2]


def test_github_gives_up_after_repeated_5xx():
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        GitHubClient("t", transport=transport, sleep=lambda s: None).get("/x")


def test_fetch_last_success():
    body = {"workflow_runs": [{"created_at": "2026-09-28T23:07:00Z"}]}
    client = GitHubClient("t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    assert fetch_last_success(client, "o/r", "daily-scrum.yml").day == 28
    empty = GitHubClient("t", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"workflow_runs": []})))
    assert fetch_last_success(empty, "o/r", "daily-scrum.yml") is None
