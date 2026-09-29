"""collect() 전체를 가짜 GitHub API(MockTransport)로 실행 — 실제 토큰 없이 수집기 배선 확인."""
from datetime import timedelta

import httpx

from conftest import NOW
from pm_agent.collector.github import GitHubClient, collect
from pm_agent.rules import build_digests, evaluate

R = "/repos/demo-team/campus-market"
Z = lambda h: (NOW - timedelta(hours=h)).isoformat().replace("+00:00", "Z")

LOG = "2026-09-30T00:00:00.0Z FAILED tests/test_auth.py::test_refresh - AssertionError\nError: exit 1"

ROUTES = {
    R: {"default_branch": "main"},
    f"{R}/commits": [
        {"sha": "aaaaaaa111", "html_url": "u/a", "author": {"login": "haedeuncha"},
         "commit": {"message": "토큰 갱신 수정 (#41)", "author": {"email": "x", "date": Z(5)}}},
        {"sha": "bbbbbbb222", "html_url": "u/b", "author": {"login": "dependabot[bot]"},
         "commit": {"message": "bump", "author": {"email": "y", "date": Z(4)}}},
        {"sha": "ccccccc333", "html_url": "u/c", "author": None,
         "commit": {"message": "외부 기여", "author": {"email": "z@x", "date": Z(3)}}},
    ],
    ("pulls", "open"): [{"number": 37, "title": "결제 리팩터링", "state": "open", "draft": False,
                         "user": {"login": "minsu-dev"}, "created_at": Z(52), "updated_at": Z(20),
                         "merged_at": None, "body": "Closes #43", "html_url": "u/37"}],
    ("pulls", "closed"): [{"number": 20, "title": "옛날 PR", "state": "closed", "user": {"login": "minsu-dev"},
                           "created_at": Z(300), "updated_at": Z(200), "merged_at": None, "html_url": "u/20"}],
    f"{R}/pulls/37/commits": [],
    f"{R}/pulls/37/reviews": [],
    f"{R}/pulls/37/requested_reviewers": {"users": [{"login": "seoyeon-park"}]},
    ("issues", "all"): [{"number": 50, "title": "PR아님", "state": "open", "created_at": Z(2), "updated_at": Z(2),
                         "html_url": "u/50", "labels": [], "assignees": []}],
    ("issues", "jiwoo-lee"): [{"number": 38, "title": "찜하기", "state": "open", "created_at": Z(120),
                               "updated_at": Z(90), "html_url": "u/38", "labels": [{"name": "feature"}],
                               "assignees": [{"login": "jiwoo-lee"}]}],
    f"{R}/issues/38/events": [{"event": "assigned", "created_at": Z(96)}],
    ("issues", "none"): [{"number": 45, "title": "알림 버그", "state": "open", "created_at": Z(48),
                          "updated_at": Z(12), "html_url": "u/45", "labels": [{"name": "bug"}], "assignees": []}],
    f"{R}/actions/runs": {"workflow_runs": [
        {"id": 1, "run_number": 144, "name": "CI", "head_branch": "main", "head_sha": "aaaaaaa111",
         "event": "push", "conclusion": "failure", "created_at": Z(5), "actor": {"login": "haedeuncha"},
         "html_url": "u/run144"},
        {"id": 2, "run_number": 145, "name": "CI", "head_branch": "dev", "head_sha": "ddddddd444",
         "event": "push", "conclusion": "success", "created_at": Z(4), "actor": {"login": "jiwoo-lee"},
         "html_url": "u/run145"}]},
    f"{R}/actions/runs/1/jobs": {"jobs": [{"id": 11, "name": "test", "conclusion": "failure",
                                            "steps": [{"name": "Run pytest", "conclusion": "failure"}]},
                                           {"id": 12, "name": "lint", "conclusion": "success", "steps": []}]},
    f"{R}/actions/jobs/11/logs": LOG,
}


FAIL_LOGS = False


def handler(req: httpx.Request):
    path, q = req.url.path, req.url.params
    if path == f"{R}/pulls":
        key = ("pulls", q["state"])
    elif path == f"{R}/issues":
        key = ("issues", "none" if q.get("assignee") == "none" else q.get("assignee") or q.get("state"))
        if key not in ROUTES:
            return httpx.Response(200, json=[])
    else:
        key = path
    if key == f"{R}/actions/jobs/11/logs" and FAIL_LOGS:
        return httpx.Response(404)
    body = ROUTES[key]
    if isinstance(body, str):
        return httpx.Response(200, text=body)
    return httpx.Response(200, json=body)


def test_collect_end_to_end(cfg):
    client = GitHubClient("t", transport=httpx.MockTransport(handler))
    raw = collect(cfg, client, NOW - timedelta(hours=24), NOW)

    assert [c.sha for c in raw.commits] == ["aaaaaaa", "ccccccc"]      # 봇 제외
    assert raw.unmapped_commits == 1
    assert raw.pull_requests[0].author == "minsu"
    assert raw.pull_requests[0].requested_reviewers == ["seoyeon"]
    assert raw.pull_requests[0].closes_issues == [43]
    assert raw.open_assigned["jiwoo"][0].assigned_at is not None
    assert raw.ci_runs[0].failed_tests == ["tests/test_auth.py::test_refresh"]
    assert raw.ci_runs[0].jobs[0].failed_step == "Run pytest"

    rules = sorted(c.rule_id for c in evaluate(raw, cfg))
    assert rules == ["R-CI-MAIN-RED", "R-ISSUE-BLOCKED", "R-ISSUE-UNOWNED", "R-PR-STALE"]
    assert any(e.kind == "review_requested" for e in build_digests(raw, cfg)["seoyeon"].today)
    assert client.calls < 300                                          # NFR-09


def test_collect_log_download_failure(cfg):
    global FAIL_LOGS
    FAIL_LOGS = True
    try:
        raw = collect(cfg, GitHubClient("t", transport=httpx.MockTransport(handler)), NOW - timedelta(hours=24), NOW)
    finally:
        FAIL_LOGS = False
    job = raw.ci_runs[0].jobs[0]
    assert job.log_tail == "" and job.failed_tests == []
