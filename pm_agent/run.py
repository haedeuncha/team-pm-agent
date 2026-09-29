"""진입점: 그래프 실행 → report.md / report.json

예)
  python -m pm_agent.run --fixture fixtures/risky_day.json            # 오프라인 (가상 팀)
  python -m pm_agent.run --since 1d                                   # 실제 팀 저장소
  python -m pm_agent.run --scheduled                                  # 정기 실행: 주말·공휴일이면 건너뜀
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
from .collector.auth import resolve_token
from .collector.github import GitHubClient, collect, fetch_last_success
from .collector.window import compute_window
from .config import load_config
from .graph import build_graph
from .llm import make_llm
from .store import last_sent_until, make_store
from .workcalendar import skip_reason


def gh_output(**values) -> None:
    """GitHub Actions 다음 job 에서 쓸 출력값."""
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def workflow_file() -> str:
    """GITHUB_WORKFLOW_REF(owner/repo/.github/workflows/x.yml@ref) 에서 파일 이름을 꺼낸다."""
    ref = os.getenv("GITHUB_WORKFLOW_REF", "")
    return ref.split("@")[0].rsplit("/", 1)[-1] if ref else "daily-scrum.yml"


def previous_until(cfg) -> datetime | None:
    """이번 수집의 시작점: ① 마지막 발송 기록 ② 워크플로 직전 성공 실행 ③ 없음(기본 기간)."""
    try:
        last = last_sent_until(make_store(cfg), cfg)
        if last:
            print(f"🗂️ 마지막 발송 리포트 기준: {last:%Y-%m-%d %H:%M} UTC 이후")
            return last
    except Exception as e:  # noqa: BLE001
        print(f"상태 저장소 조회 실패: {type(e).__name__}")
    own_repo, own_token = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_TOKEN")
    if own_repo and own_token:
        try:
            return fetch_last_success(GitHubClient(own_token), own_repo, workflow_file())
        except Exception as e:  # 첫 실행 등
            print(f"직전 성공 실행 조회 실패, 기본 기간 사용: {e}")
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Team Project PM Agent")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--fixture", help="GitHub 대신 fixture(JSON)로 실행")
    ap.add_argument("--since", help="분석 기간 (예: 1d, 7d). 없으면 직전 성공 실행 이후")
    ap.add_argument("--llm", help="fake | openai | anthropic (기본: config.yaml)")
    ap.add_argument("--model")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--scheduled", action="store_true", help="정기 실행: 주말·공휴일이면 건너뜀")
    ap.add_argument("--graph", action="store_true", help="그래프 구조(mermaid)만 출력")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if os.getenv("TEAM_REPO"):
        cfg.set_repos_from_env(os.environ["TEAM_REPO"])
    out = Path(args.out)
    now = datetime.now(timezone.utc)

    if args.scheduled and not args.fixture:
        reason = skip_reason(now, cfg)
        if reason:
            print(f"🏖️ {reason} — 정기 실행을 건너뜁니다.")
            out.with_suffix(".json").write_text(json.dumps(
                {"skipped": True, "reason": reason, "generated_at": now.isoformat(), "team": cfg.team_name},
                ensure_ascii=False, indent=2), encoding="utf-8")
            gh_output(skip="true", risks=0)
            return 0

    provider = args.llm or os.getenv("LLM_PROVIDER") or cfg.llm.provider
    model = args.model or os.getenv("LLM_MODEL") or cfg.llm.model
    llm = make_llm(provider, model, cfg.llm.temperature, display=cfg.display,
                   extra_patterns=cfg.security.extra_patterns)

    if args.fixture:
        def source():
            return load_fixture(args.fixture)
        print(f"📦 fixture 모드: {args.fixture}")
    else:
        token, method = resolve_token(cfg.repos[0].name)
        if not token:
            print("GitHub 인증 정보가 없습니다. GH_READ_TOKEN 또는 GH_APP_ID/GH_APP_PRIVATE_KEY 를 설정하거나 "
                  "--fixture 로 실행하세요.", file=sys.stderr)
            return 2
        last = None
        if not args.since:
            last = previous_until(cfg)
        since, until = compute_window(now, last_success=last, since_opt=args.since, tz=cfg.tz)
        print(f"🔎 {cfg.repo_label} ({method}) 수집 기간: {since:%Y-%m-%d %H:%M} ~ {until:%Y-%m-%d %H:%M} UTC")

        def source():
            client = GitHubClient(token, base_url=cfg.github.api_url)
            raw = collect(cfg, client, since, until)
            print(f"  GitHub API 호출 {client.calls}회")
            return raw

    app = build_graph(cfg, llm, source)
    if args.graph:
        print(app.get_graph().draw_mermaid())
        return 0

    final = app.invoke({}, {"recursion_limit": 50})
    report = final["report"]
    out.write_text(final["report_md"], encoding="utf-8")
    cost = llm.cost_usd(cfg.llm.price_per_1m_input, cfg.llm.price_per_1m_output)
    meta = {
        "skipped": False,
        "team": cfg.team_name,
        "repos": [r.name for r in cfg.repos],
        "generated_at": now.isoformat(),
        "report_date": report.date,
        "headline": report.headline,
        "trace": final.get("trace", []),
        "warnings": final.get("warnings", []),
        "risks": len(report.risks),
        "risk_rules": [f.rule_id for f in report.risks],
        "stats": report.stats,
        "window_since": final["raw"].since.isoformat(),
        "window_until": final["raw"].until.isoformat(),
        "llm": provider,
        "model": model,
        "usage": {k: dict(v) for k, v in llm.usage.items()},
        "cost_usd": cost,
    }
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    gh_output(skip="false", risks=len(report.risks))

    print("\n🧭 실행 경로: " + " → ".join(meta["trace"]))
    print(f"🔢 LLM 사용량 ({provider}{'/' + model if model else ''}) · 추정 비용 ${cost:.4f}")
    for node, u in meta["usage"].items():
        print(f"  {node:<14} calls={u['calls']} in≈{u['input']} out={u['output']}")
    print(f"✅ {args.out} 생성 완료")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
