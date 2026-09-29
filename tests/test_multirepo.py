"""여러 저장소(web / api)를 한 팀 리포트로."""
from datetime import timedelta

import httpx

from conftest import NOW
from pm_agent.collector.github import GitHubClient, _tag, collect
from pm_agent.config import RepoConfig
from pm_agent.graph import build_graph
from pm_agent.llm import FakeLLM
from pm_agent.models import RawActivity
from pm_agent.render import link_refs
from pm_agent.rules import evaluate
from test_collect_api import handler


def merged(fixture):
    web, api = _tag(fixture("normal_day"), "web"), _tag(fixture("ci_flaky"), "api")
    raw = RawActivity(repo="o/web, o/api", since=web.since, until=web.until,
                      default_branches={"web": "main", "api": "main"})
    for p in (web, api):
        raw.commits += p.commits
        raw.pull_requests += p.pull_requests
        raw.issues += p.issues
        raw.ci_runs += p.ci_runs
        for k, v in p.open_assigned.items():
            raw.open_assigned.setdefault(k, []).extend(v)
    return raw


def test_refs_do_not_collide_across_repos(fixture):
    raw = merged(fixture)
    refs = raw.ref_universe()
    assert "issue:web/41" in refs and "issue:api/41" in refs
    assert raw.find("commit:api/d4e5f6b").message.startswith("토큰 갱신")


def test_rules_per_repo(cfg, fixture):
    rules = {(c.rule_id, c.refs[0]) for c in evaluate(merged(fixture), cfg)}
    assert ("R-PR-STALE", "pr:web/33") in rules
    assert ("R-CI-MAIN-RED", "run:api/144") in rules
    assert not any(r.startswith(("run:web",)) for _, r in rules)     # web CI 는 전부 성공


def test_graph_and_links_with_aliases(cfg, fixture):
    raw = merged(fixture)
    s = build_graph(cfg, FakeLLM(display=cfg.display), lambda: raw, log=lambda *_: None).invoke({})
    assert s["trace"][-1] == "validator" and s["report"].diagnosis is not None
    md = s["report_md"]
    assert "[web#33](" in md and "[api run #144](" in md
    assert link_refs("[commit:api/d4e5f6b]", raw).startswith("[api@d4e5f6b](")


def test_collect_two_repos(cfg):
    cfg.repos = [RepoConfig(name="demo-team/campus-market", alias="web"),
                 RepoConfig(name="demo-team/campus-market", alias="api")]
    raw = collect(cfg, GitHubClient("t", transport=httpx.MockTransport(handler)), NOW - timedelta(hours=24), NOW)
    assert raw.default_branches == {"web": "main", "api": "main"}
    assert {p.ref for p in raw.pull_requests} == {"pr:web/37", "pr:api/37"}
    assert {i.ref for i in raw.open_assigned["jiwoo"]} == {"issue:web/38", "issue:api/38"}
    rules = sorted(c.rule_id for c in evaluate(raw, cfg))
    assert rules.count("R-PR-STALE") == 2 and rules.count("R-CI-MAIN-RED") == 2
