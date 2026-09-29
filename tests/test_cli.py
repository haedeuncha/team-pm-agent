"""run.py / publish.py 명령줄 실행 흐름."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import ROOT
from pm_agent import run
from pm_agent.collector import load_fixture
from pm_agent.store import LocalStore, NullStore

CFG = str(ROOT / "config.yaml")
FIX = str(ROOT / "fixtures" / "ci_flaky.json")


# ---------------------------------------------------------------- run.py
def test_run_fixture_writes_report_and_meta(tmp_path, capsys):
    out = tmp_path / "report.md"
    assert run.main(["--config", CFG, "--fixture", FIX, "--out", str(out), "--llm", "fake"]) == 0
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert "ci_diagnoser" in meta["trace"] and meta["risks"] == 3
    assert "데일리 스크럼" in out.read_text(encoding="utf-8")
    assert "실행 경로" in capsys.readouterr().out


def test_run_graph_prints_mermaid(capsys):
    assert run.main(["--config", CFG, "--fixture", FIX, "--graph"]) == 0
    assert "ci_analyst -.-> ci_diagnoser" in capsys.readouterr().out


def test_run_without_token_fails(monkeypatch, capsys):
    for k in ("GH_READ_TOKEN", "GH_APP_ID", "GH_APP_PRIVATE_KEY", "SECRETS_JSON"):
        monkeypatch.delenv(k, raising=False)
    assert run.main(["--config", CFG]) == 2
    assert "GH_READ_TOKEN" in capsys.readouterr().err


class DummyClient:
    def __init__(self, token, **kw):
        self.calls = 7


@pytest.mark.parametrize("last_success", ["ok", "error"])
def test_run_live_mode_uses_last_success(monkeypatch, tmp_path, capsys, last_success):
    seen = {}
    monkeypatch.setenv("GH_READ_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "haedeuncha/team-pm-agent")
    monkeypatch.setenv("GITHUB_TOKEN", "own")
    monkeypatch.setenv("TEAM_REPO", "demo-team/other")
    monkeypatch.setattr(run, "GitHubClient", DummyClient)
    monkeypatch.setattr(run, "make_store", lambda cfg: NullStore())      # 네트워크 없이
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))

    def fake_last(client, repo, wf):
        if last_success == "error":
            raise RuntimeError("first run")
        return datetime.now(timezone.utc) - timedelta(hours=30)

    def fake_collect(cfg, client, since, until):
        seen.update(repo=cfg.repos[0].name, hours=round((until - since).total_seconds() / 3600))
        return load_fixture(FIX)

    monkeypatch.setattr(run, "fetch_last_success", fake_last)
    monkeypatch.setattr(run, "collect", fake_collect)
    assert run.main(["--config", CFG, "--out", str(tmp_path / "r.md"), "--llm", "fake"]) == 0
    assert seen["repo"] == "demo-team/other"
    out = capsys.readouterr().out
    assert "GitHub API 호출 7회" in out
    assert "skip=false" in (tmp_path / "gh_output").read_text()
    if last_success == "ok":
        assert seen["hours"] == 30
    else:
        assert "직전 성공 실행 조회 실패" in out


def test_run_scheduled_skips_holiday(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run, "skip_reason", lambda now, cfg: "2026-10-05 개천절 대체 휴일")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "o"))
    out = tmp_path / "r.md"
    assert run.main(["--config", CFG, "--scheduled", "--out", str(out)]) == 0
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["skipped"] and not out.exists()
    assert "skip=true" in (tmp_path / "o").read_text()


def test_run_meta_has_cost(tmp_path):
    out = tmp_path / "r.md"
    run.main(["--config", CFG, "--fixture", FIX, "--out", str(out)])
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["cost_usd"] == 0 and meta["team"] == "campus-market" and "R-CI-FLAKY" in meta["risk_rules"]


def test_previous_until_prefers_last_sent_record(monkeypatch, tmp_path):
    """주말·휴일에 건너뛴 실행이 있어도 마지막 '발송' 리포트 이후를 모두 수집한다."""
    from pm_agent.config import load_config
    cfg = load_config(CFG)
    store = LocalStore(tmp_path)
    store.put("sent/campus-market/2026-10-01.json", {"window_until": "2026-09-30T23:07:00+00:00"})
    store.put("sent/campus-market/2026-09-30.json", {"generated_at": "2026-09-29T23:07:00+00:00"})
    monkeypatch.setattr(run, "make_store", lambda c: store)
    assert run.previous_until(cfg) == datetime(2026, 9, 30, 23, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(run, "make_store", lambda c: LocalStore(tmp_path / "empty"))
    for k in ("GITHUB_REPOSITORY", "GITHUB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert run.previous_until(cfg) is None

    def broken(c):
        raise RuntimeError("no token")
    monkeypatch.setattr(run, "make_store", broken)
    assert run.previous_until(cfg) is None


def test_workflow_file_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "o/pm/.github/workflows/daily-backend.yml@refs/heads/main")
    assert run.workflow_file() == "daily-backend.yml"
    monkeypatch.delenv("GITHUB_WORKFLOW_REF")
    assert run.workflow_file() == "daily-scrum.yml"
