"""운영 알림: 워크플로가 실패하면 운영 채널(config.yaml 의 alerts)로 알린다.

  python -m pm_agent.alert --stage generate
"""
from __future__ import annotations

import argparse
import os

from .config import load_config
from .notify import broadcast


def run_url() -> str | None:
    server, repo, run_id = (os.getenv(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None


def main(argv: list[str] | None = None, **send_kw) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--stage", default="unknown", help="실패한 단계 (generate / publish)")
    ap.add_argument("--message", default="")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if not cfg.alerts:
        print("alerts 채널이 설정되지 않아 알림을 보내지 않습니다.")
        return 0
    url = run_url()
    md = "\n".join(filter(None, [
        f"## 🚨 PM 에이전트 실패 — {cfg.team_name}",
        f"- 단계: **{args.stage}**",
        f"- 저장소: {cfg.repo_label}",
        f"- 실행 로그: {url}" if url else None,
        f"- 내용: {args.message}" if args.message else None,
        "- 오늘 리포트가 발송되지 않았을 수 있습니다. 로그를 확인한 뒤 Run workflow 로 다시 실행하세요.",
    ]))
    results = broadcast(cfg.alerts, md, f"[{cfg.team_name}] PM 에이전트 실패 ({args.stage})", **send_kw)
    for r in results:
        print(f"{'✅' if r.ok else '❌'} {r.channel}: {r.detail or r.messages}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
