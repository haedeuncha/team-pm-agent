"""GitHub REST 응답(JSON) → 내부 모델 변환. 네트워크 없이 테스트할 수 있는 순수 함수들."""
from __future__ import annotations

import re
from datetime import datetime

from ..config import Config
from ..models import CIRun, Commit, Issue, PullRequest, Review

ISSUE_REF_RE = re.compile(r"(?<![\w/])#(\d+)")
CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def is_bot(login: str | None, cfg: Config) -> bool:
    return bool(login) and (login in cfg.bots or login.endswith("[bot]"))


def member_key(login: str | None, cfg: Config) -> str | None:
    return cfg.member_by_login(login)


def login_or_member(login: str | None, cfg: Config) -> str:
    return cfg.member_by_login(login) or (login or "unknown")


def commit_from_api(d: dict, cfg: Config) -> Commit | None:
    """None 이면 봇 커밋(집계 제외)."""
    login = (d.get("author") or {}).get("login")
    if is_bot(login, cfg):
        return None
    info = d.get("commit") or {}
    author = cfg.member_by_login(login) or cfg.member_by_email((info.get("author") or {}).get("email"))
    message = (info.get("message") or "").splitlines()[0] if info.get("message") else ""
    when = _dt((info.get("author") or {}).get("date")) or _dt((info.get("committer") or {}).get("date"))
    return Commit(
        sha=d["sha"][:7],
        author=author,
        message=message,
        committed_at=when,
        url=d.get("html_url", ""),
        issue_refs=sorted({int(n) for n in ISSUE_REF_RE.findall(info.get("message") or "")}),
    )


def pr_from_api(d: dict, cfg: Config, *, reviews: list[dict] | None = None,
                requested: dict | None = None, commits: list[Commit] | None = None) -> PullRequest:
    state = "merged" if d.get("merged_at") else d["state"]
    req_users = (requested or {}).get("users", d.get("requested_reviewers") or [])
    return PullRequest(
        number=d["number"],
        title=d["title"],
        author=login_or_member((d.get("user") or {}).get("login"), cfg),
        state=state,
        draft=bool(d.get("draft")),
        created_at=_dt(d["created_at"]),
        updated_at=_dt(d["updated_at"]),
        merged_at=_dt(d.get("merged_at")),
        requested_reviewers=[login_or_member(u.get("login"), cfg) for u in req_users],
        reviews=[
            Review(reviewer=login_or_member((r.get("user") or {}).get("login"), cfg),
                   state=r["state"], submitted_at=_dt(r["submitted_at"]))
            for r in (reviews or []) if r.get("submitted_at") and r.get("state") in
            ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED")
        ],
        commits=commits or [],
        closes_issues=sorted({int(n) for n in CLOSES_RE.findall(d.get("body") or "")}),
        url=d["html_url"],
    )


def issues_from_api(items: list[dict], cfg: Config) -> list[Issue]:
    """이슈 목록 응답에서 PR 을 제외하고 변환한다 (TC-COL-01)."""
    out = []
    for d in items:
        if "pull_request" in d:
            continue
        out.append(Issue(
            number=d["number"],
            title=d["title"],
            state=d["state"],
            labels=[lb["name"] if isinstance(lb, dict) else lb for lb in d.get("labels", [])],
            assignees=[login_or_member(a.get("login"), cfg) for a in d.get("assignees", [])],
            created_at=_dt(d["created_at"]),
            updated_at=_dt(d.get("updated_at")),
            closed_at=_dt(d.get("closed_at")),
            closed_by=login_or_member((d.get("closed_by") or {}).get("login"), cfg) if d.get("closed_by") else None,
            url=d["html_url"],
        ))
    return out


def run_from_api(d: dict, cfg: Config) -> CIRun:
    return CIRun(
        run_id=d["id"],
        run_number=d["run_number"],
        workflow=d.get("name") or "",
        branch=d.get("head_branch") or "",
        head_sha=(d.get("head_sha") or "")[:7],
        event=d.get("event") or "",
        conclusion=d.get("conclusion"),
        created_at=_dt(d["created_at"]),
        actor=login_or_member((d.get("actor") or {}).get("login"), cfg) if d.get("actor") else None,
        url=d["html_url"],
    )


def last_assigned_at(events: list[dict]) -> datetime | None:
    times = [_dt(e["created_at"]) for e in events if e.get("event") == "assigned"]
    return max(times) if times else None
