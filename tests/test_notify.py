"""발송 채널: Discord / Slack / Teams / 이메일(Gmail SMTP)."""
import json

import httpx
import pytest

from pm_agent.config import ChannelConfig
from pm_agent.credentials import get_secret, reset_cache
from pm_agent.notify import (EmailNotifier, SkipChannel, broadcast, make_notifier, plain_links,
                             post_with_retry, split_message, to_html, to_slack_mrkdwn, to_teams_text)

MD = "# 📋 데일리 스크럼\n\n**요약**\n\n## 🚨 위험 요소\n- 🔴 **main 빌드 실패** [run #144](<https://github.com/o/r/actions/runs/1>)"


class Recorder:
    def __init__(self, status=204):
        self.posts, self.status = [], status

    def __call__(self, req: httpx.Request):
        self.posts.append((str(req.url), json.loads(req.content)))
        return httpx.Response(self.status)


def ch(type_, **kw):
    return ChannelConfig(type=type_, webhook_env="HOOK", test_webhook_env="HOOK_TEST", **kw)


# ---------------------------------------------------------------- 변환
def test_markdown_conversions():
    assert plain_links("[a](<https://x.io/1>)") == "[a](https://x.io/1)"
    slack = to_slack_mrkdwn(MD)
    assert "<https://github.com/o/r/actions/runs/1|run #144>" in slack
    assert "*📋 데일리 스크럼*" in slack and "**" not in slack
    assert "**🚨 위험 요소**" in to_teams_text(MD)
    html = to_html(MD, "t")
    assert '<a href="https://github.com/o/r/actions/runs/1">' in html and "<strong>" in html


def test_split_short_and_long():
    assert split_message("# a\n\n## b\n- c") == ["# a\n\n## b\n- c"]
    md = "# 제목\n\n" + "\n\n".join(f"## 섹션{i}\n" + "\n".join(f"- 줄 {i}-{j} " + "가" * 40 for j in range(25))
                                  for i in range(4))
    chunks = split_message(md)
    assert len(md) > 4000 and len(chunks) >= 3 and all(len(c) <= 1900 for c in chunks)
    assert all(c.startswith(("## ", "- ")) for c in chunks[1:])
    huge = "## 긴 섹션\n" + "\n".join("- " + "가" * 100 for _ in range(50)) + "\n" + "나" * 4000
    assert all(len(c) <= 1900 for c in split_message(huge)) and "".join(split_message(huge)).count("나") == 4000


# ---------------------------------------------------------------- webhook 채널
@pytest.mark.parametrize("type_,key", [("discord", "content"), ("slack", "text"), ("teams", "attachments")])
def test_webhook_channels_post_payload(monkeypatch, type_, key):
    monkeypatch.setenv("HOOK", "https://hooks.example/abc")
    rec = Recorder()
    res = make_notifier(ch(type_), transport=httpx.MockTransport(rec)).send(MD, "제목")
    assert res.ok and res.messages == 1
    url, payload = rec.posts[0]
    assert url == "https://hooks.example/abc" and key in payload
    if type_ == "discord":
        assert payload["allowed_mentions"] == {"parse": []}      # @everyone 멘션 차단
    if type_ == "teams":
        assert payload["attachments"][0]["content"]["type"] == "AdaptiveCard"


def test_dry_run_uses_test_webhook(monkeypatch):
    monkeypatch.setenv("HOOK", "https://real")
    monkeypatch.setenv("HOOK_TEST", "https://test")
    rec = Recorder()
    make_notifier(ch("discord"), dry_run=True, transport=httpx.MockTransport(rec)).send(MD, "t")
    assert rec.posts[0][0] == "https://test"


def test_missing_webhook_is_skip(monkeypatch):
    monkeypatch.delenv("HOOK", raising=False)
    with pytest.raises(SkipChannel):
        make_notifier(ch("slack")).send(MD, "t")


def test_retry_after_header_and_json():
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        if len(calls) == 2:
            return httpx.Response(429, json={"retry_after": 0.5})
        return httpx.Response(204)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        post_with_retry(http, "https://h/x", {}, waits.append)
    assert waits == [2.0, 0.5]


def test_retry_gives_up():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow"))) as http:
        with pytest.raises(RuntimeError):
            post_with_retry(http, "https://h/x", {}, lambda s: None)


def test_secrets_json_fallback(monkeypatch):
    monkeypatch.delenv("HOOK", raising=False)
    monkeypatch.setenv("SECRETS_JSON", json.dumps({"HOOK": "https://from-json"}))
    reset_cache()
    try:
        assert get_secret("HOOK") == "https://from-json"
        monkeypatch.setenv("SECRETS_JSON", "{broken")
        reset_cache()
        assert get_secret("HOOK") is None and get_secret(None) is None
    finally:
        monkeypatch.delenv("SECRETS_JSON")
        reset_cache()


# ---------------------------------------------------------------- 이메일
class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.tls, self.login_args, self.sent = host, port, False, None, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.tls = True

    def login(self, u, p):
        self.login_args = (u, p)

    def send_message(self, msg):
        self.sent.append(msg)


def email_ch(**kw):
    return ChannelConfig(type="email", name="gmail", to_env="MAIL_TO", test_to_env="MAIL_TO_TEST", **kw)


def test_gmail_smtp_send(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setenv("SMTP_USERNAME", "team.bot@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_TO", "a@x.com, b@x.com")
    res = EmailNotifier(email_ch(to=["lead@x.com"]), smtp_factory=FakeSMTP).send(MD, "[campus] 데일리 스크럼")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.tls) == ("smtp.gmail.com", 587, True)
    msg = smtp.sent[0]
    assert msg["To"] == "lead@x.com, a@x.com, b@x.com" and msg["From"] == "team.bot@gmail.com"
    assert "text/html" in [p.get_content_type() for p in msg.iter_parts()]
    assert res.ok and res.detail == "3명"


def test_email_ssl_and_dry_run(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setenv("MAIL_TO_TEST", "me@x.com")
    EmailNotifier(email_ch(use_ssl=True, smtp_port=465, from_addr="PM Bot <bot@x.com>"),
                  smtp_factory=FakeSMTP, dry_run=True).send(MD, "t")
    smtp = FakeSMTP.instances[0]
    assert smtp.tls is False and smtp.sent[0]["To"] == "me@x.com"


def test_email_skips_without_credentials_or_recipients(monkeypatch):
    for k in ("SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_TO", "MAIL_TO_TEST"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SkipChannel):
        EmailNotifier(email_ch()).send(MD, "t")
    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    with pytest.raises(SkipChannel):
        EmailNotifier(email_ch()).send(MD, "t")
    with pytest.raises(SkipChannel):
        EmailNotifier(email_ch(), dry_run=True).send(MD, "t")


# ---------------------------------------------------------------- broadcast
def test_broadcast_isolates_failures_and_redacts_urls(monkeypatch):
    monkeypatch.setenv("HOOK", "https://discord.com/api/webhooks/123/SECRET")
    chans = [ch("discord"), ch("slack", enabled=False), ChannelConfig(type="teams", webhook_env="NOPE")]
    res = broadcast(chans, MD, "t", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert [r.channel for r in res] == ["discord", "teams"]
    assert not res[0].ok and "SECRET" not in res[0].detail
    assert res[1].ok and res[1].messages == 0 and "건너뜀" in res[1].detail


def test_broadcast_only_filter(monkeypatch):
    monkeypatch.setenv("HOOK", "https://h")
    rec = Recorder()
    res = broadcast([ch("discord"), ch("slack")], MD, "t", only="slack", transport=httpx.MockTransport(rec))
    assert [r.channel for r in res] == ["slack"] and len(rec.posts) == 1
