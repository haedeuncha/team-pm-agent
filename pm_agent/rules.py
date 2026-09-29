"""위험 판정 규칙과 팀원별 근거 데이터 (docs/PLAN.md 5장, docs/TEST_PLAN.md 2.2). LLM 없음."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .config import Config
from .models import EvidenceItem, MemberDigest, RawActivity, RiskCandidate


def _hours(td: timedelta) -> float:
    return round(td.total_seconds() / 3600, 1)


# ------------------------------------------------------------------ 규칙
def rule_pr(raw: RawActivity, cfg: Config) -> list[RiskCandidate]:
    th, now, out = cfg.thresholds, raw.until, []
    for p in raw.pull_requests:
        if p.state != "open":
            continue
        idle = now - p.updated_at
        if idle >= timedelta(days=th.pr_abandoned_days):
            out.append(RiskCandidate(id="", rule_id="R-PR-ABANDONED", area="pr", severity="high",
                                     refs=[p.ref], owner=p.author,
                                     facts={"title": p.title, "idle_days": round(idle.total_seconds() / 86400, 1)}))
            continue  # 방치 PR 은 오래된 PR 과 중복 보고하지 않음
        if p.draft:
            continue
        reviews = [r for r in p.reviews if r.reviewer != p.author]
        age = now - p.created_at
        if not reviews and age >= timedelta(hours=th.pr_stale_hours):
            out.append(RiskCandidate(id="", rule_id="R-PR-STALE", area="pr", severity="medium",
                                     refs=[p.ref], owner=p.author,
                                     facts={"title": p.title, "hours_without_review": _hours(age),
                                            "requested_reviewers": p.requested_reviewers}))
    return out


def rule_issue(raw: RawActivity, cfg: Config) -> list[RiskCandidate]:
    th, now, out = cfg.thresholds, raw.until, []
    seen: set[str] = set()
    for member, issues in raw.open_assigned.items():
        for i in issues:
            if i.ref in seen:
                continue
            seen.add(i.ref)
            start = i.assigned_at or i.created_at
            limit = timedelta(days=th.issue_blocked_days)
            last = i.last_linked_activity
            if now - start >= limit and (last is None or now - last >= limit):
                linked_prs = [p.ref for p in raw.pull_requests
                              if p.repo == i.repo and i.number in p.closes_issues and p.state == "open"]
                out.append(RiskCandidate(id="", rule_id="R-ISSUE-BLOCKED", area="issue", severity="medium",
                                         refs=[i.ref, *linked_prs], owner=member,
                                         facts={"title": i.title, "assigned_days": round((now - start).total_seconds() / 86400, 1),
                                                "last_activity": last.isoformat() if last else None,
                                                "open_linked_prs": linked_prs}))
    for i in raw.open_unassigned_bugs:
        if "bug" in i.labels and not i.assignees:
            out.append(RiskCandidate(id="", rule_id="R-ISSUE-UNOWNED", area="issue", severity="medium",
                                     refs=[i.ref], owner=None,
                                     facts={"title": i.title, "age_days": round((now - i.created_at).total_seconds() / 86400, 1)}))
    return out


def rule_ci(raw: RawActivity, cfg: Config) -> list[RiskCandidate]:
    th, out = cfg.thresholds, []
    runs = [r for r in raw.ci_runs if r.conclusion in ("success", "failure")]
    by_wf: dict[tuple[str, str], list] = defaultdict(list)
    for r in runs:
        by_wf[(r.repo, r.workflow)].append(r)

    for (repo, wf_name), wf_runs in by_wf.items():
        wf = f"{repo}/{wf_name}" if repo else wf_name
        wf_runs.sort(key=lambda r: r.created_at)
        # R-CI-MAIN-RED: 기본 브랜치의 마지막 실행이 실패
        main_runs = [r for r in wf_runs if r.branch == raw.branch_of(repo)]
        if main_runs and main_runs[-1].conclusion == "failure":
            last = main_runs[-1]
            out.append(RiskCandidate(id="", rule_id="R-CI-MAIN-RED", area="ci", severity="critical",
                                     refs=[last.ref], owner=last.actor,
                                     facts={"workflow": wf, "branch": last.branch,
                                            "failed_tests": last.failed_tests,
                                            "failed_step": next((j.failed_step for j in last.jobs if j.failed_step), None)}))
        # R-CI-REPEAT: 최근 N회 중 같은 테스트가 k회 이상 실패
        window = wf_runs[-th.ci_repeat_window:]
        counts: dict[str, list] = defaultdict(list)
        for r in window:
            for t in set(r.failed_tests):
                counts[t].append(r)
        for test, failed_runs in counts.items():
            if len(failed_runs) >= th.ci_repeat_min_failures:
                out.append(RiskCandidate(id="", rule_id="R-CI-REPEAT", area="ci", severity="high",
                                         refs=[r.ref for r in failed_runs], owner=None,
                                         facts={"workflow": wf, "test": test, "failures": len(failed_runs),
                                                "window": len(window)}))
        # R-CI-FLAKY: 같은 SHA 에서 성공과 실패가 모두 있음
        by_sha: dict[str, list] = defaultdict(list)
        for r in wf_runs:
            by_sha[r.head_sha].append(r)
        for sha, sha_runs in by_sha.items():
            outcomes = {r.conclusion for r in sha_runs}
            if {"success", "failure"} <= outcomes:
                tests = sorted({t for r in sha_runs for t in r.failed_tests})
                out.append(RiskCandidate(id="", rule_id="R-CI-FLAKY", area="ci", severity="medium",
                                         refs=[r.ref for r in sha_runs], owner=None,
                                         facts={"workflow": wf, "sha": sha, "tests": tests}))
    return out


def evaluate(raw: RawActivity, cfg: Config) -> list[RiskCandidate]:
    cands = rule_ci(raw, cfg) + rule_pr(raw, cfg) + rule_issue(raw, cfg)
    for n, c in enumerate(cands, 1):
        c.id = f"c{n}"
    return cands


# ------------------------------------------------------------------ 근거 데이터
def build_digests(raw: RawActivity, cfg: Config) -> dict[str, MemberDigest]:
    d = {k: MemberDigest(member=k, display=m.display) for k, m in cfg.members.items()}

    # 어제 한 일 (FR-05)
    merged_shas: set[str] = set()
    for p in raw.pull_requests:
        if p.author in d and p.state == "merged" and raw.in_window(p.merged_at):
            d[p.author].yesterday.append(EvidenceItem(ref=p.ref, kind="pr_merged", title=p.title, url=p.url))
            merged_shas |= {c.ref for c in p.commits}
        elif p.author in d and raw.in_window(p.created_at):
            d[p.author].yesterday.append(EvidenceItem(ref=p.ref, kind="pr_opened", title=p.title, url=p.url))
        for r in p.reviews:
            if r.reviewer in d and r.reviewer != p.author and raw.in_window(r.submitted_at):
                if not any(e.ref == p.ref and e.kind == "review" for e in d[r.reviewer].yesterday):
                    d[r.reviewer].yesterday.append(EvidenceItem(
                        ref=p.ref, kind="review", title=f"{p.title} 리뷰({r.state})", url=p.url))
    for c in raw.all_commits():
        if c.author in d and raw.in_window(c.committed_at) and c.ref not in merged_shas:
            d[c.author].yesterday.append(EvidenceItem(ref=c.ref, kind="commit", title=c.message, url=c.url))
    for i in raw.issues:
        if i.closed_by in d and raw.in_window(i.closed_at):
            d[i.closed_by].yesterday.append(EvidenceItem(ref=i.ref, kind="issue_closed", title=i.title, url=i.url))

    # 오늘 할 일 (FR-06): 할당 이슈, 리뷰 요청, Draft PR 만
    for member, issues in raw.open_assigned.items():
        if member in d:
            for i in issues:
                d[member].today.append(EvidenceItem(ref=i.ref, kind="issue_assigned", title=i.title, url=i.url))
    for p in raw.pull_requests:
        if p.state != "open":
            continue
        for rv in p.requested_reviewers:
            if rv in d:
                d[rv].today.append(EvidenceItem(ref=p.ref, kind="review_requested", title=p.title, url=p.url))
        if p.draft and p.author in d:
            d[p.author].today.append(EvidenceItem(ref=p.ref, kind="draft_pr", title=p.title, url=p.url))
    return d


def activity_areas(raw: RawActivity) -> set[str]:
    """기간 안에 변화가 있었던 영역."""
    areas: set[str] = set()
    if any(raw.in_window(p.updated_at) for p in raw.pull_requests) or raw.commits:
        areas.add("pr")
    if any(raw.in_window(r.created_at) for r in raw.ci_runs):
        areas.add("ci")
    if raw.issues:
        areas.add("issue")
    return areas


def compute_stats(raw: RawActivity) -> dict[str, int | float | str]:
    window_runs = [r for r in raw.ci_runs if raw.in_window(r.created_at) and r.conclusion in ("success", "failure")]
    ok = sum(1 for r in window_runs if r.conclusion == "success")
    return {
        "commits": sum(1 for c in raw.all_commits() if raw.in_window(c.committed_at)),
        "merged_prs": sum(1 for p in raw.pull_requests if raw.in_window(p.merged_at)),
        "opened_prs": sum(1 for p in raw.pull_requests if raw.in_window(p.created_at)),
        "new_issues": sum(1 for i in raw.issues if raw.in_window(i.created_at)),
        "closed_issues": sum(1 for i in raw.issues if raw.in_window(i.closed_at)),
        "ci_runs": len(window_runs),
        "ci_success_rate": f"{round(ok / len(window_runs) * 100)}%" if window_runs else "-",
        "unmapped_commits": raw.unmapped_commits,
    }
