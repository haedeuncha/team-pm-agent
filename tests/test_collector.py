"""TC-COL: 수집기 (docs/TEST_PLAN.md 2.1)."""
from datetime import datetime, timezone

import httpx

from conftest import NOW
from pm_agent.collector import logparse
from pm_agent.collector.github import GitHubClient
from pm_agent.collector.normalize import commit_from_api, issues_from_api, pr_from_api
from pm_agent.collector.window import compute_window


def test_col01_issues_exclude_pull_requests(cfg):
    items = [
        {"number": 1, "title": "이슈", "state": "open", "created_at": "2026-09-29T00:00:00Z", "html_url": "u"},
        {"number": 2, "title": "PR", "state": "open", "created_at": "2026-09-29T00:00:00Z", "html_url": "u",
         "pull_request": {"url": "x"}},
    ]
    assert [i.number for i in issues_from_api(items, cfg)] == [1]


def test_col02_pagination_follows_link_header():
    pages = {1: [{"n": 1}, {"n": 2}], 2: [{"n": 3}], 3: [{"n": 4}]}

    def handler(req: httpx.Request):
        page = int(req.url.params.get("page", 1))
        headers = {}
        if page < 3:
            headers["link"] = f'<https://api.github.com/items?page={page + 1}>; rel="next"'
        return httpx.Response(200, json=pages[page], headers=headers)

    client = GitHubClient("t", transport=httpx.MockTransport(handler))
    assert [d["n"] for d in client.paginate("/items")] == [1, 2, 3, 4]
    assert client.calls == 3


def test_col02b_rate_limit_waits_once():
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return httpx.Response(200, json={"ok": True})

    client = GitHubClient("t", transport=httpx.MockTransport(handler), sleep=waits.append)
    assert client.get("/x") == {"ok": True}
    assert waits == [3.0]


def _commit(login=None, email="x@example.com", msg="fix"):
    return {"sha": "abcdef1234", "html_url": "u", "author": {"login": login} if login else None,
            "commit": {"message": msg, "author": {"email": email, "date": "2026-09-29T10:00:00Z"}}}


def test_col03_commit_mapped_by_email(cfg):
    cfg.members["minsu"].emails = ["minsu@example.com"]
    c = commit_from_api(_commit(login=None, email="minsu@example.com"), cfg)
    assert c.author == "minsu"


def test_col03b_commit_mapped_by_login(cfg):
    assert commit_from_api(_commit(login="jiwoo-lee"), cfg).author == "jiwoo"


def test_col04_bot_commit_excluded(cfg):
    assert commit_from_api(_commit(login="dependabot[bot]"), cfg) is None


def test_col05_monday_uses_last_success_from_friday():
    fri = datetime(2026, 10, 1, 23, 7, tzinfo=timezone.utc)   # KST 금 08:07
    mon = datetime(2026, 10, 4, 23, 7, tzinfo=timezone.utc)   # KST 월 08:07
    assert compute_window(mon, last_success=fri) == (fri, mon)


def test_col05b_monday_without_history_uses_72h():
    mon = datetime(2026, 10, 4, 23, 7, tzinfo=timezone.utc)
    since, _ = compute_window(mon)
    assert (mon - since).total_seconds() == 72 * 3600


def test_col06_weekday_without_history_uses_24h():
    since, until = compute_window(NOW)   # KST 수요일
    assert (until - since).total_seconds() == 24 * 3600


def test_col06b_manual_since_overrides():
    since, until = compute_window(NOW, last_success=NOW, since_opt="7d")
    assert (until - since).days == 7


def test_col07_pytest_failed_tests_with_ansi_and_timestamp():
    log = ("2026-09-30T00:07:12.3Z \x1b[31mFAILED tests/test_auth.py::test_refresh - AssertionError\x1b[0m\n"
           "2026-09-30T00:07:12.4Z FAILED tests/test_auth.py::test_refresh - again\n")
    assert logparse.failed_tests(log, "pytest") == ["tests/test_auth.py::test_refresh"]
    assert "\x1b" not in logparse.tail(log)


def test_col07b_jest_and_junit_patterns():
    assert logparse.failed_tests("  ● AuthService › refreshes token", "jest") == ["AuthService › refreshes token"]
    assert logparse.failed_tests("AuthTest > refresh() FAILED", "junit") == ["AuthTest > refresh()"]


def test_col08_issue_refs_from_commit_message(cfg):
    c = commit_from_api(_commit(login="haedeuncha", msg="fix login (#41) refs #42\n\nbody #99"), cfg)
    assert c.issue_refs == [41, 42, 99]
    assert c.message == "fix login (#41) refs #42"


def test_col09_closes_issues_from_pr_body(cfg):
    d = {"number": 5, "title": "t", "state": "open", "user": {"login": "minsu-dev"},
         "created_at": "2026-09-29T00:00:00Z", "updated_at": "2026-09-29T00:00:00Z",
         "body": "Closes #41, fixes #43 and mentions #50", "html_url": "u"}
    p = pr_from_api(d, cfg)
    assert p.closes_issues == [41, 43]
    assert p.author == "minsu"


def test_run_with_unusual_conclusion_is_accepted(cfg):
    """실데이터 회귀: 승인 대기 중인 실행은 conclusion='action_required' 로 온다."""
    from pm_agent.collector.normalize import run_from_api
    for c in ("action_required", "neutral", "stale", "startup_failure", None):
        r = run_from_api({"id": 1, "run_number": 1, "name": "daily-scrum", "head_branch": "main",
                          "head_sha": "abcdef1", "event": "workflow_dispatch", "conclusion": c,
                          "created_at": "2026-09-29T08:00:00Z", "html_url": "u"}, cfg)
        assert r.conclusion == c
