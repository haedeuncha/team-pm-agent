"""run.py / publish.py 명령줄 실행 흐름."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import ROOT
from pm_agent import publish, run
from pm_agent.collector import load_fixture

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
    monkeypatch.delenv("GH_READ_TOKEN", raising=False)
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

    def fake_last(client, repo, wf):
        if last_success == "error":
            raise RuntimeError("first run")
        return datetime.now(timezone.utc) - timedelta(hours=30)

    def fake_collect(cfg, client, since, until):
        seen.update(repo=cfg.team_repo, hours=round((until - since).total_seconds() / 3600))
        return load_fixture(FIX)

    monkeypatch.setattr(run, "fetch_last_success", fake_last)
    monkeypatch.setattr(run, "collect", fake_collect)
    assert run.main(["--config", CFG, "--out", str(tmp_path / "r.md"), "--llm", "fake"]) == 0
    assert seen["repo"] == "demo-team/other"
    out = capsys.readouterr().out
    assert "GitHub API 호출 7회" in out
    if last_success == "ok":
        assert seen["hours"] == 30
    else:
        assert "직전 성공 실행 조회 실패" in out


# ---------------------------------------------------------------- publish.py
def write_report(tmp_path, generated_at):
    md = tmp_path / "report.md"
    md.write_text("# 제목\n\n## 섹션\n- 내용", encoding="utf-8")
    md.with_suffix(".json").write_text(json.dumps({"generated_at": generated_at.isoformat()}), encoding="utf-8")
    return str(md)


def test_publish_print_mode(tmp_path, capsys):
    path = write_report(tmp_path, datetime.now(timezone.utc))
    assert publish.main([path, "--config", CFG, "--print"]) == 0
    assert "[1/1]" in capsys.readouterr().out


def test_publish_skips_expired_report(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(publish, "send", lambda *a, **k: pytest.fail("만료된 리포트를 보내면 안 됨"))
    path = write_report(tmp_path, datetime.now(timezone.utc) - timedelta(days=2))
    assert publish.main([path, "--config", CFG]) == 0
    assert "승인 마감" in capsys.readouterr().out


def test_publish_without_webhook(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert publish.main([write_report(tmp_path, datetime.now(timezone.utc)), "--config", CFG]) == 2


def test_publish_sends(tmp_path, monkeypatch, capsys):
    sent = {}
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    monkeypatch.setattr(publish, "send", lambda chunks, url: sent.setdefault("n", len(chunks)))
    assert publish.main([write_report(tmp_path, datetime.now(timezone.utc)), "--config", CFG]) == 0
    assert sent["n"] == 1 and "전송 완료" in capsys.readouterr().out


def test_split_very_long_section_and_line():
    md = "## 긴 섹션\n" + "\n".join("- " + "가" * 100 for _ in range(50)) + "\n" + "나" * 4000
    chunks = publish.split_message(md, limit=1900)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(chunks).count("나") == 4000


def test_send_gives_up_after_repeated_429():
    import httpx
    transport = httpx.MockTransport(lambda req: httpx.Response(429, json={"retry_after": 0}))
    with pytest.raises(RuntimeError):
        publish.send(["x"], "https://discord.test/hook", transport=transport, sleep=lambda s: None)
