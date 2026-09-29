"""승인 후 발송 (docs/PLAN.md 6장, docs/OPERATIONS.md).

1. 정기 실행을 건너뛴 날(주말·공휴일)이면 아무것도 하지 않음
2. 승인 마감(approval_deadline)이 지났으면 발송하지 않음
3. 같은 날짜 리포트를 이미 보냈으면 다시 보내지 않음 (상태 저장소, --force 로 무시)
4. config.yaml 의 channels 전부에 발송 (Discord / Slack / Teams / 이메일)
5. 발송 표시와 리포트 이력을 상태 저장소에 기록
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector.window import KST
from .config import load_config
from .notify import broadcast, split_message  # noqa: F401  (split_message 는 하위 호환용)
from .store import NullStore, history_key, make_store, sent_key


def is_expired(generated_at: datetime, deadline_hhmm: str, now: datetime, tz: ZoneInfo = KST) -> bool:
    """생성일(팀 시간대)의 마감 시각이 지났으면 True."""
    gen = generated_at.astimezone(tz)
    hh, mm = map(int, deadline_hhmm.split(":"))
    deadline = gen.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if deadline <= gen:          # 마감 이후에 만든 리포트(수동 실행)는 다음 날 같은 시각까지 유효
        deadline += timedelta(days=1)
    return now.astimezone(tz) > deadline


def step_summary(lines: list[str]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None, *, store=None, **send_kw) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", nargs="?", default="report.md")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--print", action="store_true", help="보내지 않고 나눈 결과만 출력")
    ap.add_argument("--dry-run", action="store_true", help="각 채널의 테스트 대상(test_*_env)으로만 발송")
    ap.add_argument("--channel", help="이 채널만 발송 (type 또는 name)")
    ap.add_argument("--force", action="store_true", help="이미 보낸 날짜여도 다시 발송")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    report_path = Path(args.report)
    meta_path = report_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    if meta.get("skipped"):
        print(f"🏖️ 건너뛴 실행입니다: {meta.get('reason')}")
        return 0
    now = datetime.now(timezone.utc)
    if meta.get("generated_at") and not args.print:
        gen = datetime.fromisoformat(meta["generated_at"])
        if is_expired(gen, cfg.approval_deadline, now, cfg.tz):
            print(f"⏰ 승인 마감({cfg.approval_deadline} {cfg.timezone})이 지나 발송하지 않습니다.")
            step_summary([f"⏰ 승인 마감({cfg.approval_deadline})이 지나 발송하지 않았습니다."])
            return 0

    md = report_path.read_text(encoding="utf-8")
    if args.print:
        for i, c in enumerate(split_message(md), 1):
            print(f"----- [{i}] {len(c)}자 -----\n{c}")
        return 0

    report_date = (meta.get("report_date") or now.astimezone(cfg.tz).strftime("%Y-%m-%d"))[:10]
    if store is None:
        try:
            store = make_store(cfg)
        except RuntimeError as e:
            print(f"⚠️ 상태 저장소를 쓸 수 없어 중복 발송 방지·이력 기록 없이 진행합니다: {e}")
            store = NullStore()
    key = sent_key(cfg, report_date)
    if not args.dry_run and not args.force:
        prev = store.get(key)
        if prev:
            print(f"🔁 {report_date} 리포트는 이미 {prev.get('sent_at')}에 발송했습니다. (--force 로 재발송)")
            return 0

    title = f"[{cfg.team_name}] 데일리 스크럼 — {meta.get('report_date') or report_date}"
    if args.dry_run:
        title = "[테스트] " + title
    results = broadcast(cfg.channels, md, title, dry_run=args.dry_run, only=args.channel, **send_kw)

    lines = ["| 채널 | 결과 | 메시지 | 비고 |", "|---|---|---|---|"]
    for r in results:
        icon = "✅" if r.ok and r.messages else ("⏭️" if r.ok else "❌")
        print(f"{icon} {r.channel}: {r.messages}개 {r.detail}")
        lines.append(f"| {r.channel} | {icon} | {r.messages} | {r.detail} |")
    step_summary(["### 📨 발송 결과", *lines])

    sent = [r for r in results if r.ok and r.messages]
    failed = [r for r in results if not r.ok]
    if sent and not args.dry_run:
        record = {"sent_at": now.isoformat(), "channels": [r.channel for r in sent],
                  "failed": [r.channel for r in failed], "run_id": os.getenv("GITHUB_RUN_ID")}
        try:
            store.put(key, record)
            store.put(history_key(cfg, report_date), {**meta, **record})
        except Exception as e:  # 발송은 끝났으므로 기록 실패는 경고만
            print(f"⚠️ 발송 기록 저장 실패: {type(e).__name__}")
    if not results:
        print("켜진 채널이 없습니다. config.yaml 의 channels 를 확인하세요.")
        return 2
    if failed:
        return 1
    if not sent:
        print("모든 채널을 건너뛰었습니다(비밀값 없음).")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
