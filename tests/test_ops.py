"""운영 기능: 상태 저장소, 근무일 달력, GitHub App 인증, 실패 알림, 설정 검증."""
import base64
import json
from datetime import date, datetime, timezone

import httpx
import pytest

from conftest import ROOT
from pm_agent import alert
from pm_agent.collector.auth import app_jwt, resolve_token
from pm_agent.collector.github import GitHubClient
from pm_agent.config import Config, load_config
from pm_agent.store import GitHubBranchStore, LocalStore, NullStore, make_store
from pm_agent.workcalendar import skip_reason

CFG = str(ROOT / "config.yaml")
UTC = timezone.utc


# ---------------------------------------------------------------- 상태 저장소
def test_local_store_roundtrip(tmp_path):
    s = LocalStore(tmp_path)
    assert s.get("sent/t/2026-09-30.json") is None and s.list("sent") == []
    s.put("sent/t/2026-09-30.json", {"a": "한글"})
    assert s.get("sent/t/2026-09-30.json") == {"a": "한글"}
    assert s.list("sent") == ["sent/t/2026-09-30.json"]
    with pytest.raises(ValueError):
        s.put("../escape.json", {})


def test_null_store():
    s = NullStore()
    s.put("k", {})
    assert s.get("k") is None and s.list("") == []


class FakeGitHub:
    """Contents / Git refs API 를 흉내 내는 MockTransport 핸들러."""

    def __init__(self, branch_exists=False):
        self.files, self.branch_exists, self.created_ref = {}, branch_exists, None

    def __call__(self, req: httpx.Request):
        p, m = req.url.path, req.method
        if p == "/repos/o/pm/git/ref/heads/pm-agent-state":
            return httpx.Response(200 if self.branch_exists else 404, json={"object": {"sha": "s1"}})
        if p == "/repos/o/pm":
            return httpx.Response(200, json={"default_branch": "main"})
        if p == "/repos/o/pm/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "abc"}})
        if p == "/repos/o/pm/git/refs" and m == "POST":
            self.created_ref = json.loads(req.content)
            self.branch_exists = True
            return httpx.Response(201, json={})
        if p.startswith("/repos/o/pm/contents/"):
            key = p.removeprefix("/repos/o/pm/contents/")
            if m == "GET":
                if key == "sent":
                    return httpx.Response(200, json=[{"path": k, "type": "file"} for k in self.files if k.startswith("sent/")])
                if key in self.files:
                    return httpx.Response(200, json=self.files[key])
                return httpx.Response(404)
            if m == "PUT":
                body = json.loads(req.content)
                if key in self.files:
                    assert body["sha"] == self.files[key]["sha"]
                self.files[key] = {"content": body["content"], "sha": f"sha{len(self.files)}", "path": key}
                return httpx.Response(200, json={})
        return httpx.Response(500)


def test_github_branch_store_creates_branch_and_updates():
    gh = FakeGitHub()
    store = GitHubBranchStore(GitHubClient("t", transport=httpx.MockTransport(gh)), "o/pm", "pm-agent-state")
    assert store.get("sent/x.json") is None and store.list("history") == []
    store.put("sent/x.json", {"n": 1})
    assert gh.created_ref == {"ref": "refs/heads/pm-agent-state", "sha": "abc"}
    store.put("sent/x.json", {"n": 2})            # 기존 파일은 sha 를 넘겨 갱신
    assert store.get("sent/x.json") == {"n": 2}
    assert json.loads(base64.b64decode(gh.files["sent/x.json"]["content"])) == {"n": 2}
    assert store.list("sent") == ["sent/x.json"]


def test_github_store_errors_propagate():
    boom = GitHubClient("t", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    store = GitHubBranchStore(boom, "o/pm", "b")
    for call in (lambda: store.get("k"), lambda: store.list("sent"), lambda: store.put("k", {})):
        with pytest.raises(httpx.HTTPStatusError):
            call()


def test_make_store(monkeypatch, tmp_path):
    cfg = load_config(CFG)
    cfg.state.backend = "none"
    assert isinstance(make_store(cfg), NullStore)
    cfg.state.backend, cfg.state.path = "local", str(tmp_path)
    assert isinstance(make_store(cfg), LocalStore)
    cfg.state.backend = "github"
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        make_store(cfg)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/pm")
    st = make_store(cfg)
    assert isinstance(st, GitHubBranchStore) and st.repo == "o/pm"


# ---------------------------------------------------------------- 근무일
def test_skip_reason_weekend_holiday_and_company_day():
    cfg = load_config(CFG)
    assert skip_reason(datetime(2026, 9, 29, 23, 7, tzinfo=UTC), cfg) is None          # KST 9/30 수
    assert "주말" in skip_reason(datetime(2026, 10, 2, 23, 7, tzinfo=UTC), cfg)          # KST 10/3 토
    assert "대체" in skip_reason(datetime(2026, 10, 4, 23, 7, tzinfo=UTC), cfg)          # 개천절 대체공휴일
    assert "추석" in skip_reason(datetime(2026, 9, 24, 23, 7, tzinfo=UTC), cfg)          # KST 9/25
    cfg.schedule.extra_holidays = [date(2026, 9, 30)]
    assert "회사 휴일" in skip_reason(datetime(2026, 9, 29, 23, 7, tzinfo=UTC), cfg)
    cfg.schedule.extra_holidays, cfg.schedule.skip_holidays = [], False
    assert skip_reason(datetime(2026, 10, 4, 23, 7, tzinfo=UTC), cfg) is None


# ---------------------------------------------------------------- GitHub App 인증
@pytest.fixture(scope="module")
def rsa_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem


def test_app_jwt_is_valid_rs256(rsa_pem):
    import jwt
    key, pem = rsa_pem
    token = app_jwt("12345", pem, now=1_800_000_000)
    claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims["iss"] == "12345" and claims["exp"] - claims["iat"] == 600


def test_resolve_token_prefers_pat_then_app(monkeypatch, rsa_pem):
    for k in ("GH_READ_TOKEN", "GH_APP_ID", "GH_APP_PRIVATE_KEY", "GH_APP_INSTALLATION_ID", "SECRETS_JSON"):
        monkeypatch.delenv(k, raising=False)
    assert resolve_token("o/r") == (None, "none")
    monkeypatch.setenv("GH_READ_TOKEN", "pat")
    assert resolve_token("o/r") == ("pat", "token")
    monkeypatch.delenv("GH_READ_TOKEN")
    monkeypatch.setenv("GH_APP_ID", "1")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", rsa_pem[1].replace("\n", "\\n"))   # 한 줄로 저장된 키도 허용
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.headers["authorization"][:10]))
        if req.url.path == "/repos/o/r/installation":
            return httpx.Response(200, json={"id": 77})
        return httpx.Response(201, json={"token": "ghs_installation"})
    factory = lambda tok: GitHubClient(tok, transport=httpx.MockTransport(handler))
    assert resolve_token("o/r", factory) == ("ghs_installation", "github-app")
    assert [s[1] for s in seen] == ["/repos/o/r/installation", "/app/installations/77/access_tokens"]
    assert seen[0][2] == "Bearer eyJ"


# ---------------------------------------------------------------- 실패 알림
def test_alert_sends_to_ops_channel(monkeypatch, capsys):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.test/ops")
    for k, v in {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/pm", "GITHUB_RUN_ID": "9"}.items():
        monkeypatch.setenv(k, v)
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content)["content"])
        return httpx.Response(204)
    assert alert.main(["--config", CFG, "--stage", "generate"], transport=httpx.MockTransport(handler)) == 0
    assert "generate" in bodies[0] and "actions/runs/9" in bodies[0]


def test_alert_without_channels(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text((ROOT / "config.yaml").read_text(encoding="utf-8").replace(
        "alerts:\n  - type: discord\n    webhook_env: ALERT_WEBHOOK_URL", "alerts: []"), encoding="utf-8")
    assert alert.main(["--config", str(cfg)]) == 0
    assert "알림을 보내지 않습니다" in capsys.readouterr().out


def test_alert_failure_returns_1(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.test/ops")
    assert alert.main(["--config", CFG], transport=httpx.MockTransport(lambda r: httpx.Response(500))) == 1


# ---------------------------------------------------------------- 설정 검증
BASE = {"leader": "a", "members": {"a": {"display": "A", "github": "a"}}}


def test_config_validation():
    assert Config.model_validate({**BASE, "team_repo": "o/r"}).repos[0].name == "o/r"      # 하위 호환
    with pytest.raises(ValueError):
        Config.model_validate(BASE)                                                        # 저장소 없음
    with pytest.raises(ValueError):
        Config.model_validate({**BASE, "repos": [{"name": "o/a"}, {"name": "o/b"}]})      # alias 없음
    with pytest.raises(ValueError):
        Config.model_validate({**BASE, "team_repo": "o/r", "leader": "ghost"})
    c = Config.model_validate({**BASE, "team_repo": "o/r", "approval_deadline_kst": "11:00"})
    assert c.approval_deadline == "11:00"


def test_team_repo_env_override():
    c = Config.model_validate({**BASE, "team_repo": "o/r"})
    c.set_repos_from_env("web=o/web, api=o/api")
    assert [(r.alias, r.name) for r in c.repos] == [("web", "o/web"), ("api", "o/api")]
    c.set_repos_from_env("o/single")
    assert c.repo_label == "o/single"
