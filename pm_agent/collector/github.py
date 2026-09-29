"""GitHub REST API 수집기 (docs/DATA_SPEC.md 2장). LLM 을 쓰지 않는다."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Callable, Iterator

import httpx

from ..config import Config
from ..models import CIJob, CIRun, Commit, Issue, PullRequest, RawActivity
from . import logparse
from .normalize import (_dt, commit_from_api, issues_from_api, last_assigned_at,
                        pr_from_api, run_from_api)

API = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=API, headers=headers, timeout=30,
                                 transport=transport, follow_redirects=True)
        self.sleep = sleep
        self.calls = 0

    # ---- 저수준 요청 (재시도 포함, docs/AGENTS.md 7장)
    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        rate_waited = False
        for attempt in range(4):
            self.calls += 1
            resp = self.http.get(url, params=params)
            if resp.status_code in (403, 429) and not rate_waited and (
                    resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-remaining") == "0"):
                wait = float(resp.headers.get("retry-after") or
                             max(0, int(resp.headers.get("x-ratelimit-reset", "0")) - time.time()))
                self.sleep(min(wait, 120))
                rate_waited = True
                continue
            if resp.status_code >= 500 and attempt < 3:
                self.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def get(self, url: str, params: dict | None = None):
        return self._request(url, params).json()

    def get_text(self, url: str) -> str:
        return self._request(url).text

    def paginate(self, url: str, params: dict | None = None, *, key: str | None = None,
                 stop: Callable[[dict], bool] | None = None) -> Iterator[dict]:
        """Link 헤더의 rel="next" 를 따라가며 항목을 하나씩 돌려준다 (TC-COL-02)."""
        params = {"per_page": 100, **(params or {})}
        next_url: str | None = url
        while next_url:
            resp = self._request(next_url, params)
            params = None  # next 링크에 쿼리가 이미 포함됨
            data = resp.json()
            items = data[key] if key else data
            for item in items:
                if stop and stop(item):
                    return
                yield item
            next_url = resp.links.get("next", {}).get("url")


# ------------------------------------------------------------------ 창 계산용
def fetch_last_success(client: GitHubClient, own_repo: str, workflow_file: str) -> datetime | None:
    data = client.get(f"/repos/{own_repo}/actions/workflows/{workflow_file}/runs",
                      {"status": "success", "per_page": 1})
    runs = data.get("workflow_runs", [])
    return _dt(runs[0]["created_at"]) if runs else None


# ------------------------------------------------------------------ 본 수집
def collect(cfg: Config, client: GitHubClient, since: datetime, until: datetime) -> RawActivity:
    repo = cfg.team_repo
    base = f"/repos/{repo}"
    default_branch = client.get(base).get("default_branch", "main")
    lookback = min(since, until - timedelta(days=cfg.thresholds.issue_blocked_days))

    # A1 기본 브랜치 커밋 (막힌 작업 판정을 위해 lookback 까지)
    lookback_commits: list[Commit] = []
    unmapped = 0
    for d in client.paginate(f"{base}/commits", {"since": lookback.isoformat(), "until": until.isoformat()}):
        c = commit_from_api(d, cfg)
        if c is None:
            continue
        lookback_commits.append(c)
    window_commits = [c for c in lookback_commits if since <= c.committed_at <= until]
    unmapped += sum(1 for c in window_commits if c.author is None)

    # A2~A5 PR: 열린 PR 전부 + 기간 내 갱신된 닫힌 PR
    prs: list[PullRequest] = []
    raw_prs = list(client.paginate(f"{base}/pulls", {"state": "open"}))
    raw_prs += list(client.paginate(
        f"{base}/pulls", {"state": "closed", "sort": "updated", "direction": "desc"},
        stop=lambda d: _dt(d["updated_at"]) < since))
    for d in raw_prs:
        n = d["number"]
        pr_commits = [c for c in (commit_from_api(x, cfg) for x in client.paginate(f"{base}/pulls/{n}/commits")) if c]
        reviews = list(client.paginate(f"{base}/pulls/{n}/reviews"))
        requested = client.get(f"{base}/pulls/{n}/requested_reviewers") if d["state"] == "open" else {"users": []}
        prs.append(pr_from_api(d, cfg, reviews=reviews, requested=requested, commits=pr_commits))

    # A6 기간 내 변경된 이슈
    issues = issues_from_api(list(client.paginate(f"{base}/issues", {"state": "all", "since": since.isoformat()})), cfg)
    issues = [i for i in issues if (i.updated_at or i.created_at) >= since]

    # A7 팀원별 열린 할당 이슈 (+ assigned 이벤트 시각)
    open_assigned: dict[str, list[Issue]] = {}
    for key, m in cfg.members.items():
        lst = issues_from_api(list(client.paginate(f"{base}/issues", {"state": "open", "assignee": m.github})), cfg)
        for i in lst:
            i.assigned_at = last_assigned_at(list(client.paginate(f"{base}/issues/{i.number}/events")))
        open_assigned[key] = lst
    unassigned_bugs = issues_from_api(list(client.paginate(
        f"{base}/issues", {"state": "open", "labels": "bug", "assignee": "none"})), cfg)

    # 이슈별 마지막 연결 활동
    _link_activity(open_assigned, lookback_commits, prs)

    # A8~A10 CI
    runs = _collect_runs(cfg, client, base, since)

    return RawActivity(
        repo=repo, default_branch=default_branch, since=since, until=until,
        commits=window_commits, pull_requests=prs, issues=issues,
        open_assigned=open_assigned, open_unassigned_bugs=unassigned_bugs,
        ci_runs=runs, unmapped_commits=unmapped,
    )


def _link_activity(open_assigned: dict[str, list[Issue]], commits: list[Commit], prs: list[PullRequest]) -> None:
    last: dict[int, datetime] = {}

    def bump(n: int, t: datetime) -> None:
        if n not in last or t > last[n]:
            last[n] = t

    for c in commits:
        for n in c.issue_refs:
            bump(n, c.committed_at)
    for p in prs:
        for n in p.closes_issues:
            bump(n, p.updated_at)
        for c in p.commits:
            for n in c.issue_refs:
                bump(n, c.committed_at)
    for lst in open_assigned.values():
        for i in lst:
            i.last_linked_activity = last.get(i.number)


def _collect_runs(cfg: Config, client: GitHubClient, base: str, since: datetime) -> list[CIRun]:
    by_id: dict[int, CIRun] = {}
    recent = client.get(f"{base}/actions/runs", {"per_page": cfg.thresholds.ci_recent_runs})
    for d in recent.get("workflow_runs", []):
        by_id[d["id"]] = run_from_api(d, cfg)
    for d in client.paginate(f"{base}/actions/runs", {"created": f">={since.date().isoformat()}"},
                             key="workflow_runs"):
        by_id.setdefault(d["id"], run_from_api(d, cfg))
    for run in by_id.values():
        if run.conclusion != "failure":
            continue
        jobs = client.get(f"{base}/actions/runs/{run.run_id}/jobs").get("jobs", [])
        for j in jobs:
            if j.get("conclusion") != "failure":
                continue
            step = next((s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"), None)
            try:
                log = client.get_text(f"{base}/actions/jobs/{j['id']}/logs")
            except httpx.HTTPError:
                log = ""
            run.jobs.append(CIJob(
                job_id=j["id"], name=j["name"], conclusion="failure", failed_step=step,
                failed_tests=logparse.failed_tests(log, cfg.test_log_pattern) if log else [],
                log_tail=logparse.tail(log) if log else "",
            ))
    return sorted(by_id.values(), key=lambda r: r.created_at)
