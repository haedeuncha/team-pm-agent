"""상태 저장소: 중복 발송 방지 표시(sent/)와 리포트 이력(history/).

- none  : 저장하지 않음 (기본, 개발용)
- local : 로컬 디렉터리의 JSON 파일 (Docker 볼륨, 서버 cron)
- github: pm-agent 저장소의 별도 브랜치에 JSON 파일로 커밋 (GitHub Actions 에서 상태 유지)
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx

from .config import Config


class Store:
    def get(self, key: str) -> dict | None:
        return None

    def put(self, key: str, data: dict) -> None:
        return None

    def list(self, prefix: str) -> list[str]:
        return []


class NullStore(Store):
    pass


class LocalStore(Store):
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"잘못된 키: {key}")
        return p

    def get(self, key):
        p = self._path(key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key, data):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self, prefix):
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace(os.sep, "/") for p in base.rglob("*.json"))


class GitHubBranchStore(Store):
    """Contents API 로 전용 브랜치에 파일을 읽고 쓴다. 필요 권한: contents: write."""

    def __init__(self, client, repo: str, branch: str):
        self.client, self.repo, self.branch = client, repo, branch
        self._branch_ready = False

    def _url(self, key: str) -> str:
        return f"/repos/{self.repo}/contents/{key}"

    def _get_raw(self, key: str) -> dict | None:
        try:
            return self.client.get(self._url(key), {"ref": self.branch})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get(self, key):
        raw = self._get_raw(key)
        if not raw:
            return None
        return json.loads(base64.b64decode(raw["content"]).decode("utf-8"))

    def _ensure_branch(self) -> None:
        if self._branch_ready:
            return
        try:
            self.client.get(f"/repos/{self.repo}/git/ref/heads/{self.branch}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            default = self.client.get(f"/repos/{self.repo}").get("default_branch", "main")
            sha = self.client.get(f"/repos/{self.repo}/git/ref/heads/{default}")["object"]["sha"]
            self.client.send("POST", f"/repos/{self.repo}/git/refs",
                             {"ref": f"refs/heads/{self.branch}", "sha": sha})
        self._branch_ready = True

    def put(self, key, data):
        self._ensure_branch()
        existing = self._get_raw(key)
        body = {
            "message": f"pm-agent: {key}",
            "content": base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode(),
            "branch": self.branch,
        }
        if existing:
            body["sha"] = existing["sha"]
        self.client.send("PUT", self._url(key), body)

    def list(self, prefix):
        try:
            items = self.client.get(self._url(prefix.rstrip("/")), {"ref": self.branch})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
        return sorted(i["path"] for i in items if i.get("type") == "file")


def make_store(cfg: Config, client_factory=None) -> Store:
    st = cfg.state
    if st.backend == "local":
        return LocalStore(st.path)
    if st.backend == "github":
        repo = st.repo or os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GITHUB_TOKEN")
        if not repo or not token:
            raise RuntimeError("state.backend=github 에는 GITHUB_REPOSITORY 와 GITHUB_TOKEN 이 필요합니다")
        if client_factory is None:
            from .collector.github import GitHubClient
            client_factory = GitHubClient
        return GitHubBranchStore(client_factory(token), repo, st.branch)
    return NullStore()


def sent_key(cfg: Config, report_date: str) -> str:
    return f"sent/{cfg.team_name}/{report_date[:10]}.json"


def history_key(cfg: Config, report_date: str) -> str:
    return f"history/{cfg.team_name}/{report_date[:10]}.json"


def last_sent_until(store: Store, cfg: Config):
    """마지막으로 '실제 발송된' 리포트가 다룬 기간의 끝. 다음 수집은 여기서부터 시작한다.

    주말·공휴일에 건너뛴 실행이나 팀장이 거절한 실행은 기록이 없으므로,
    그 사이 활동이 다음 리포트에 모두 포함된다.
    """
    from datetime import datetime
    keys = store.list(f"sent/{cfg.team_name}")
    if not keys:
        return None
    rec = store.get(keys[-1]) or {}
    value = rec.get("window_until") or rec.get("generated_at")
    return datetime.fromisoformat(value) if value else None
