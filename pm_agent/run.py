"""진입점: 그래프 실행 → report.md / report.json

예)
  python -m pm_agent.run --fixture fixtures/risky_day.json            # 오프라인 (가상 팀)
  python -m pm_agent.run --since 1d                                   # 실제 팀 저장소
  python -m pm_agent.run --fixture fixtures/ci_flaky.json --llm openai --model gpt-4o-mini
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .collector import load_fixture
from .collector.github import GitHubClient, collect, fetch_last_success
from .collector.window import compute_window
from .config import load_config
from .graph import build_graph
from .llm import make_llm


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Team Project PM Agent")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--fixture", help="GitHub 대신 fixture(JSON)로 실행")
    ap.add_argument("--since", help="분석 기간 (예: 1d, 7d). 없으면 직전 성공 실행 이후")
    ap.add_argument("--llm", help="fake | openai | anthropic (기본: config.yaml)")
    ap.add_argument("--model")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--graph", action="store_true", help="그래프 구조(mermaid)만 출력")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if os.getenv("TEAM_REPO"):
        cfg.team_repo = os.environ["TEAM_REPO"]
    provider = args.llm or os.getenv("LLM_PROVIDER") or cfg.llm.provider
    model = args.model or os.getenv("LLM_MODEL") or cfg.llm.model
    llm = make_llm(provider, model, cfg.llm.temperature, display=cfg.display)

    if args.fixture:
        def source():
            return load_fixture(args.fixture)
        print(f"📦 fixture 모드: {args.fixture}")
    else:
        token = os.getenv("GH_READ_TOKEN")
        if not token:
            print("GH_READ_TOKEN 이 없습니다. --fixture 로 실행하거나 토큰을 설정하세요.", file=sys.stderr)
            return 2
        now = datetime.now(timezone.utc)
        last = None
        own_repo, own_token = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_TOKEN")
        if own_repo and own_token and not args.since:
            try:
                last = fetch_last_success(GitHubClient(own_token), own_repo, "daily-scrum.yml")
            except Exception as e:  # 첫 실행 등
                print(f"직전 성공 실행 조회 실패, 기본 기간 사용: {e}")
        since, until = compute_window(now, last_success=last, since_opt=args.since)
        print(f"🔎 {cfg.team_repo} 수집 기간: {since:%Y-%m-%d %H:%M} ~ {until:%Y-%m-%d %H:%M} UTC")

        def source():
            client = GitHubClient(token)
            raw = collect(cfg, client, since, until)
            print(f"  GitHub API 호출 {client.calls}회")
            return raw

    app = build_graph(cfg, llm, source)
    if args.graph:
        print(app.get_graph().draw_mermaid())
        return 0

    final = app.invoke({}, {"recursion_limit": 50})
    Path(args.out).write_text(final["report_md"], encoding="utf-8")
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_date": final["report"].date,
        "trace": final.get("trace", []),
        "warnings": final.get("warnings", []),
        "risks": len(final["report"].risks),
        "llm": provider,
        "usage": {k: dict(v) for k, v in llm.usage.items()},
    }
    Path(args.out).with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n🧭 실행 경로: " + " → ".join(meta["trace"]))
    print("🔢 LLM 사용량 (" + provider + ")")
    for node, u in meta["usage"].items():
        print(f"  {node:<14} calls={u['calls']} in≈{u['input']} out={u['output']}")
    print(f"✅ {args.out} 생성 완료")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
