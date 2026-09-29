"""발송 채널 (Discord / Slack / Microsoft Teams / 이메일-SMTP·Gmail).

모든 채널은 같은 Markdown 리포트를 받아 각 서비스 형식으로 바꿔 보낸다.
채널은 config.yaml 의 ``channels`` 에서 켜고 끈다. 비밀값은 ``*_env`` 에 적은 이름으로 읽는다.
"""
from __future__ import annotations

import re
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

import httpx

from .config import ChannelConfig
from .credentials import get_secret
from .security import redact

# ------------------------------------------------------------------ Markdown 변환
LINK_RE = re.compile(r"\[([^\]]+)\]\(<?([^)>\s]+)>?\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.M)


def plain_links(md: str) -> str:
    """[t](<u>) → [t](u). Discord 전용 미리보기 억제 문법을 일반 Markdown 으로."""
    return LINK_RE.sub(lambda m: f"[{m.group(1)}]({m.group(2)})", md)


def to_slack_mrkdwn(md: str) -> str:
    out = LINK_RE.sub(lambda m: f"<{m.group(2)}|{m.group(1)}>", md)
    out = HEADING_RE.sub(lambda m: f"*{m.group(2).strip()}*", out)
    out = BOLD_RE.sub(r"*\1*", out)
    return out


def to_teams_text(md: str) -> str:
    out = plain_links(md)
    out = HEADING_RE.sub(lambda m: f"**{m.group(2).strip()}**", out)
    return out


def to_html(md: str, title: str) -> str:
    import markdown
    body = markdown.markdown(plain_links(md), extensions=["fenced_code", "sane_lists"])
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>'
            f'<body style="font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;line-height:1.5;'
            f'max-width:760px">{body}</body></html>')


# ------------------------------------------------------------------ 분할
def split_message(md: str, limit: int = 1900) -> list[str]:
    """## 섹션 단위로 나누고, 그래도 길면 줄 단위로 나눈다."""
    sections, cur = [], []
    for line in md.splitlines():
        if line.startswith("## ") and cur:
            sections.append("\n".join(cur).strip())
            cur = []
        cur.append(line)
    if cur:
        sections.append("\n".join(cur).strip())

    chunks: list[str] = []
    buf = ""
    for sec in sections:
        pieces = [sec] if len(sec) <= limit else _split_long(sec, limit)
        for p in pieces:
            if buf and len(buf) + 2 + len(p) > limit:
                chunks.append(buf)
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def _split_long(text: str, limit: int) -> list[str]:
    out, buf = [], ""
    for line in text.splitlines():
        while len(line) > limit:
            out.append(line[:limit])
            line = line[limit:]
        if buf and len(buf) + 1 + len(line) > limit:
            out.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out


# ------------------------------------------------------------------ 채널
@dataclass
class SendResult:
    channel: str
    ok: bool
    messages: int = 0
    detail: str = ""


class SkipChannel(Exception):
    """설정이 비어 있어 이 채널을 건너뜀 (오류 아님)."""


def post_with_retry(http: httpx.Client, url: str, payload: dict,
                    sleep: Callable[[float], None] = time.sleep, attempts: int = 3) -> None:
    for _ in range(attempts):
        resp = http.post(url, json=payload)
        if resp.status_code == 429:
            wait = resp.headers.get("retry-after")
            if wait is None:
                try:
                    wait = resp.json().get("retry_after", 1)
                except ValueError:
                    wait = 1
            sleep(float(wait))
            continue
        resp.raise_for_status()
        return
    raise RuntimeError(f"429 가 계속되어 전송 실패: {url.split('/')[2]}")


class Notifier:
    limit = 1900

    def __init__(self, ch: ChannelConfig, *, dry_run: bool = False,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        self.ch, self.dry_run, self.transport, self.sleep = ch, dry_run, transport, sleep

    def webhook(self) -> str:
        env = self.ch.test_webhook_env if self.dry_run else self.ch.webhook_env
        url = get_secret(env)
        if not url:
            raise SkipChannel(f"{'테스트 ' if self.dry_run else ''}웹훅 비밀값 {env or '(미설정)'} 없음")
        return url

    def payloads(self, md: str, title: str) -> list[dict]:  # pragma: no cover - 하위 클래스가 구현
        raise NotImplementedError

    def send(self, md: str, title: str) -> SendResult:
        url = self.webhook()
        payloads = self.payloads(md, title)
        with httpx.Client(timeout=15, transport=self.transport) as http:
            for p in payloads:
                post_with_retry(http, url, p, self.sleep)
        return SendResult(self.ch.label, True, len(payloads))


class DiscordNotifier(Notifier):
    limit = 1900   # Discord 2000자 제한

    def payloads(self, md, title):
        return [{"content": c, "allowed_mentions": {"parse": []}} for c in split_message(md, self.limit)]


class SlackNotifier(Notifier):
    limit = 3500

    def payloads(self, md, title):
        text = to_slack_mrkdwn(md)
        return [{"text": c, "unfurl_links": False, "unfurl_media": False} for c in split_message(text, self.limit)]


class TeamsNotifier(Notifier):
    """Teams 'Workflows'(Power Automate) 웹훅용 Adaptive Card."""
    limit = 12000

    def payloads(self, md, title):
        out = []
        for c in split_message(to_teams_text(md), self.limit):
            card = {"type": "AdaptiveCard", "version": "1.4",
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "body": [{"type": "TextBlock", "text": c, "wrap": True}]}
            out.append({"type": "message", "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]})
        return out


class EmailNotifier(Notifier):
    """SMTP 메일. Gmail 은 2단계 인증 + 앱 비밀번호, smtp.gmail.com:587(STARTTLS)."""

    def __init__(self, ch, *, smtp_factory: Callable | None = None, **kw):
        super().__init__(ch, **kw)
        self.smtp_factory = smtp_factory

    def recipients(self) -> list[str]:
        if self.dry_run:
            raw = get_secret(self.ch.test_to_env) or ""
            to = [x.strip() for x in raw.split(",") if x.strip()]
            if not to:
                raise SkipChannel(f"테스트 수신자 {self.ch.test_to_env or '(미설정)'} 없음")
            return to
        to = list(self.ch.to)
        to += [x.strip() for x in (get_secret(self.ch.to_env) or "").split(",") if x.strip()]
        if not to:
            raise SkipChannel("수신자(to / to_env) 없음")
        return to

    def send(self, md, title):
        user, password = get_secret(self.ch.username_env), get_secret(self.ch.password_env)
        if not user or not password:
            raise SkipChannel(f"SMTP 계정 비밀값({self.ch.username_env}/{self.ch.password_env}) 없음")
        to = self.recipients()
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self.ch.from_addr or user
        msg["To"] = ", ".join(to)
        msg.set_content(plain_links(md))
        msg.add_alternative(to_html(md, title), subtype="html")
        factory = self.smtp_factory or (smtplib.SMTP_SSL if self.ch.use_ssl else smtplib.SMTP)
        with factory(self.ch.smtp_host, self.ch.smtp_port, timeout=30) as smtp:
            if not self.ch.use_ssl:
                smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        return SendResult(self.ch.label, True, 1, f"{len(to)}명")


NOTIFIERS: dict[str, type[Notifier]] = {
    "discord": DiscordNotifier, "slack": SlackNotifier, "teams": TeamsNotifier, "email": EmailNotifier,
}


def make_notifier(ch: ChannelConfig, **kw) -> Notifier:
    return NOTIFIERS[ch.type](ch, **kw)


def broadcast(channels: list[ChannelConfig], md: str, title: str, *, dry_run: bool = False,
              only: str | None = None, **kw) -> list[SendResult]:
    """켜진 채널 모두에 보낸다. 한 채널 실패가 다른 채널 발송을 막지 않는다."""
    results = []
    for ch in channels:
        if not ch.enabled or (only and only not in (ch.type, ch.label)):
            continue
        try:
            results.append(make_notifier(ch, dry_run=dry_run, **kw).send(md, title))
        except SkipChannel as e:
            results.append(SendResult(ch.label, True, 0, f"건너뜀: {e}"))
        except Exception as e:  # noqa: BLE001 - 채널별 실패를 모아 보고
            # 오류 메시지에 웹훅 URL 이 들어갈 수 있으므로 가린다
            results.append(SendResult(ch.label, False, 0, redact(f"{type(e).__name__}: {e}")))
    return results
