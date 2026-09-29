"""승인 후 발송: Discord 웹훅 (docs/PLAN.md 6장).

- 2000자 제한 → 섹션(##) 단위로 나눠 전송 (FR-13)
- 429 → retry_after 만큼 기다렸다 재전송 (TC-PUB-02)
- 승인 마감(approval_deadline_kst)이 지났으면 발송하지 않음 (승인 만료)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from .collector.window import KST
from .config import load_config

LIMIT = 1900  # Discord 2000자 제한에 여유를 둠


def split_message(md: str, limit: int = LIMIT) -> list[str]:
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
        while len(line) > limit:            # 한 줄이 너무 긴 극단적 경우
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


def is_expired(generated_at: datetime, deadline_hhmm: str, now: datetime) -> bool:
    """생성일(KST)의 마감 시각이 지났으면 True."""
    gen = generated_at.astimezone(KST)
    hh, mm = map(int, deadline_hhmm.split(":"))
    deadline = gen.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if deadline <= gen:          # 마감 이후에 만든 리포트(수동 실행)는 다음 날 같은 시각까지 유효
        deadline += timedelta(days=1)
    return now.astimezone(KST) > deadline


def send(chunks: list[str], webhook: str, *, transport: httpx.BaseTransport | None = None,
         sleep: Callable[[float], None] = time.sleep) -> int:
    sent = 0
    with httpx.Client(timeout=15, transport=transport) as http:
        for chunk in chunks:
            for _ in range(3):
                resp = http.post(webhook, json={"content": chunk, "allowed_mentions": {"parse": []}})
                if resp.status_code == 429:
                    sleep(float(resp.json().get("retry_after", 1)))
                    continue
                resp.raise_for_status()
                sent += 1
                break
            else:
                raise RuntimeError("Discord 429 가 계속되어 전송 실패")
    return sent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", nargs="?", default="report.md")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--print", action="store_true", help="보내지 않고 나눈 결과만 출력")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    md = Path(args.report).read_text(encoding="utf-8")
    meta_path = Path(args.report).with_suffix(".json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        gen = datetime.fromisoformat(meta["generated_at"])
        if is_expired(gen, cfg.approval_deadline_kst, datetime.now(timezone.utc)):
            print(f"⏰ 승인 마감({cfg.approval_deadline_kst} KST)이 지나 발송하지 않습니다.")
            return 0

    chunks = split_message(md)
    if args.print:
        for i, c in enumerate(chunks, 1):
            print(f"----- [{i}/{len(chunks)}] {len(c)}자 -----\n{c}")
        return 0
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL 이 없습니다.", file=sys.stderr)
        return 2
    n = send(chunks, webhook)
    print(f"📨 Discord 로 {n}개 메시지 전송 완료")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
