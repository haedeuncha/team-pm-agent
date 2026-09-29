"""publish: 건너뜀 / 승인 마감 / 중복 발송 방지 / 이력 기록 / 채널 결과."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from conftest import ROOT
from pm_agent import publish
from pm_agent.store import LocalStore

CFG = str(ROOT / "config.yaml")
KST = ZoneInfo("Asia/Seoul")


def write(tmp_path, **meta):
    md = tmp_path / "report.md"
    md.write_text("# 제목\n\n## 섹션\n- 내용", encoding="utf-8")
    base = {"generated_at": datetime.now(timezone.utc).isoformat(), "report_date": "2026-09-30 (수)", "risks": 1}
    md.with_suffix(".json").write_text(json.dumps({**base, **meta}), encoding="utf-8")
    return str(md)


@pytest.fixture
def hooks(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/real")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL_TEST", "https://discord.test/test")
    posts = []

    def handler(req):
        posts.append(str(req.url))
        return httpx.Response(204)
    return posts, httpx.MockTransport(handler)


def test_send_records_sent_and_history(tmp_path, hooks, capsys):
    posts, transport = hooks
    store = LocalStore(tmp_path / "state")
    assert publish.main([write(tmp_path), "--config", CFG], store=store, transport=transport) == 0
    assert posts == ["https://discord.test/real"]
    sent = store.get("sent/campus-market/2026-09-30.json")
    assert sent["channels"] == ["discord"]
    assert store.get("history/campus-market/2026-09-30.json")["risks"] == 1
    # 같은 날 두 번째 실행은 보내지 않음
    assert publish.main([write(tmp_path), "--config", CFG], store=store, transport=transport) == 0
    assert len(posts) == 1 and "이미" in capsys.readouterr().out
    # --force 면 다시 보냄
    publish.main([write(tmp_path), "--config", CFG, "--force"], store=store, transport=transport)
    assert len(posts) == 2


def test_dry_run_goes_to_test_hook_and_is_not_recorded(tmp_path, hooks):
    posts, transport = hooks
    store = LocalStore(tmp_path / "state")
    assert publish.main([write(tmp_path), "--config", CFG, "--dry-run"], store=store, transport=transport) == 0
    assert posts == ["https://discord.test/test"] and store.list("sent") == []


def test_skipped_run_does_nothing(tmp_path, hooks):
    posts, transport = hooks
    path = write(tmp_path, skipped=True, reason="주말")
    assert publish.main([path, "--config", CFG], store=LocalStore(tmp_path), transport=transport) == 0
    assert posts == []


def test_expired_report_not_sent(tmp_path, hooks, capsys, monkeypatch):
    posts, transport = hooks
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert publish.main([write(tmp_path, generated_at=old), "--config", CFG],
                        store=LocalStore(tmp_path), transport=transport) == 0
    assert posts == [] and "승인 마감" in summary.read_text(encoding="utf-8")


def test_print_mode(tmp_path, capsys):
    assert publish.main([write(tmp_path), "--config", CFG, "--print"]) == 0
    assert "[1]" in capsys.readouterr().out


def test_channel_failure_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/real")
    store = LocalStore(tmp_path / "s")
    rc = publish.main([write(tmp_path), "--config", CFG], store=store,
                      transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert rc == 1 and store.list("sent") == []


def test_all_channels_skipped_returns_2(tmp_path, monkeypatch):
    for k in ("DISCORD_WEBHOOK_URL", "SECRETS_JSON"):
        monkeypatch.delenv(k, raising=False)
    assert publish.main([write(tmp_path), "--config", CFG], store=LocalStore(tmp_path)) == 2


def test_no_enabled_channel_returns_2(tmp_path):
    assert publish.main([write(tmp_path), "--config", CFG, "--channel", "nothing"], store=LocalStore(tmp_path)) == 2


def test_record_failure_is_only_a_warning(tmp_path, hooks, capsys):
    _, transport = hooks

    class BrokenStore(LocalStore):
        def put(self, key, data):
            raise OSError("disk full")
    assert publish.main([write(tmp_path), "--config", CFG], store=BrokenStore(tmp_path), transport=transport) == 0
    assert "발송 기록 저장 실패" in capsys.readouterr().out


def kst(day, h, m=0):
    return datetime(2026, 9 if day <= 30 else 10, day if day <= 30 else day - 30, h, m, tzinfo=KST)


def test_approval_deadline():
    gen = kst(30, 8, 7)
    assert not publish.is_expired(gen, "12:00", kst(30, 11, 59))
    assert publish.is_expired(gen, "12:00", kst(30, 12, 1))
    late = kst(30, 15, 0)                     # 마감 뒤 수동 실행 → 다음 날 마감까지
    assert not publish.is_expired(late, "12:00", kst(31, 11, 59))
    assert publish.is_expired(late, "12:00", kst(31, 12, 1))
    ny = ZoneInfo("America/New_York")         # 팀 시간대 설정
    assert publish.is_expired(datetime(2026, 9, 30, 8, tzinfo=ny), "12:00", datetime(2026, 9, 30, 12, 30, tzinfo=ny), ny)


def test_store_unavailable_falls_back(tmp_path, hooks, monkeypatch, capsys):
    posts, transport = hooks
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    assert publish.main([write(tmp_path), "--config", CFG], transport=transport) == 0   # config: backend=github
    assert posts and "상태 저장소를 쓸 수 없어" in capsys.readouterr().out
