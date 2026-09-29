"""TC-RULE: 위험 판정 규칙 경계값 (docs/TEST_PLAN.md 2.2)."""
from conftest import ago
from pm_agent.models import CIJob, CIRun, Issue, PullRequest, Review
from pm_agent.rules import build_digests, evaluate


def rules_of(raw, cfg):
    return [c.rule_id for c in evaluate(raw, cfg)]


def _pr(created, updated=None, reviews=(), draft=False):
    return PullRequest(number=1, title="t", author="minsu", state="open", draft=draft,
                       created_at=created, updated_at=updated or ago(hours=1),
                       reviews=list(reviews), url="u")


# ---- R-PR-STALE
def test_pr_stale_boundary(cfg, empty_raw):
    empty_raw.pull_requests = [_pr(ago(hours=48, minutes=1))]
    assert rules_of(empty_raw, cfg) == ["R-PR-STALE"]
    empty_raw.pull_requests = [_pr(ago(hours=47, minutes=59))]
    assert rules_of(empty_raw, cfg) == []


def test_pr_stale_not_when_reviewed_or_draft(cfg, empty_raw):
    rv = Review(reviewer="jiwoo", state="COMMENTED", submitted_at=ago(hours=2))
    empty_raw.pull_requests = [_pr(ago(hours=60), reviews=[rv]), _pr(ago(hours=60), draft=True)]
    assert rules_of(empty_raw, cfg) == []


def test_pr_self_review_does_not_count(cfg, empty_raw):
    rv = Review(reviewer="minsu", state="COMMENTED", submitted_at=ago(hours=2))
    empty_raw.pull_requests = [_pr(ago(hours=60), reviews=[rv])]
    assert rules_of(empty_raw, cfg) == ["R-PR-STALE"]


# ---- R-PR-ABANDONED
def test_pr_abandoned_boundary(cfg, empty_raw):
    empty_raw.pull_requests = [_pr(ago(days=9), updated=ago(days=5, minutes=1))]
    assert rules_of(empty_raw, cfg) == ["R-PR-ABANDONED"]      # 방치면 STALE 과 중복 보고 안 함
    empty_raw.pull_requests = [_pr(ago(days=9), updated=ago(days=4, hours=23))]
    assert rules_of(empty_raw, cfg) == ["R-PR-STALE"]


# ---- R-ISSUE-BLOCKED
def _issue(n=38, assigned=None, linked=None, labels=(), assignees=("jiwoo",)):
    return Issue(number=n, title="t", state="open", labels=list(labels), assignees=list(assignees),
                 created_at=ago(days=10), assigned_at=assigned, last_linked_activity=linked, url="u")


def test_issue_blocked_boundary(cfg, empty_raw):
    empty_raw.open_assigned = {"jiwoo": [_issue(assigned=ago(days=3, minutes=1))]}
    assert rules_of(empty_raw, cfg) == ["R-ISSUE-BLOCKED"]
    empty_raw.open_assigned = {"jiwoo": [_issue(assigned=ago(days=2, hours=23))]}
    assert rules_of(empty_raw, cfg) == []


def test_issue_not_blocked_with_recent_commit(cfg, empty_raw):
    empty_raw.open_assigned = {"jiwoo": [_issue(assigned=ago(days=5), linked=ago(days=1))]}
    assert rules_of(empty_raw, cfg) == []


# ---- R-ISSUE-UNOWNED
def test_issue_unowned(cfg, empty_raw):
    empty_raw.open_unassigned_bugs = [_issue(n=45, labels=["bug"], assignees=())]
    assert rules_of(empty_raw, cfg) == ["R-ISSUE-UNOWNED"]
    empty_raw.open_unassigned_bugs = [_issue(n=45, labels=["feature"], assignees=())]
    assert rules_of(empty_raw, cfg) == []


# ---- CI
def _run(n, conclusion, sha=None, branch="main", tests=()):
    jobs = [CIJob(job_id=n, name="test", conclusion="failure", failed_tests=list(tests))] if tests else []
    return CIRun(run_id=n, run_number=n, workflow="CI", branch=branch, head_sha=sha or f"s{n}",
                 conclusion=conclusion, created_at=ago(hours=100 - n), jobs=jobs, url="u")


T = "tests/test_auth.py::test_refresh"


def test_ci_repeat_boundary(cfg, empty_raw):
    empty_raw.ci_runs = [_run(1, "failure", tests=[T]), _run(2, "success"), _run(3, "failure", tests=[T]),
                         _run(4, "failure", tests=[T], branch="dev"), _run(5, "success")]
    assert rules_of(empty_raw, cfg) == ["R-CI-REPEAT"]
    empty_raw.ci_runs[0] = _run(1, "success")
    assert rules_of(empty_raw, cfg) == []


def test_ci_flaky_same_sha(cfg, empty_raw):
    empty_raw.ci_runs = [_run(1, "success", sha="abc"), _run(2, "failure", sha="abc", branch="dev", tests=[T]),
                         _run(3, "success")]
    assert rules_of(empty_raw, cfg) == ["R-CI-FLAKY"]
    empty_raw.ci_runs[1] = _run(2, "failure", sha="xyz", branch="dev", tests=[T])
    assert rules_of(empty_raw, cfg) == []


def test_ci_main_red_and_recovered(cfg, empty_raw):
    empty_raw.ci_runs = [_run(1, "success"), _run(2, "failure")]
    assert rules_of(empty_raw, cfg) == ["R-CI-MAIN-RED"]
    empty_raw.ci_runs.append(_run(3, "success"))
    assert rules_of(empty_raw, cfg) == []


def test_threshold_from_config(cfg, empty_raw):
    cfg.thresholds.pr_stale_hours = 24                        # FR-15
    empty_raw.pull_requests = [_pr(ago(hours=30))]
    assert rules_of(empty_raw, cfg) == ["R-PR-STALE"]


def test_candidate_ids_are_sequential(cfg, fixture):
    ids = [c.id for c in evaluate(fixture("risky_day"), cfg)]
    assert ids == [f"c{i}" for i in range(1, len(ids) + 1)]


# ---- 근거 데이터 (FR-05, FR-06)
def test_digest_today_only_assigned_review_draft(cfg, fixture):
    digests = build_digests(fixture("risky_day"), cfg)
    kinds = {e.kind for d in digests.values() for e in d.today}
    assert kinds <= {"issue_assigned", "review_requested", "draft_pr"}
    assert "draft_pr" in {e.kind for e in digests["jiwoo"].today}


def test_digest_merged_pr_commits_not_duplicated(cfg, fixture):
    d = build_digests(fixture("normal_day"), cfg)["haeden"]
    refs = [e.ref for e in d.yesterday]
    assert "pr:35" in refs and "commit:b2c3d4e" not in refs   # 머지된 PR 커밋은 PR 한 줄로
