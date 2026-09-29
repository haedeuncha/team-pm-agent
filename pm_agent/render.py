"""Report → Markdown (Jinja2). LLM 은 마크다운을 직접 만들지 않는다."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import REF_RE, RawActivity, Report

TEMPLATES = Path(__file__).resolve().parent / "templates"
SEV_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def link_refs(text: str, raw: RawActivity) -> str:
    """[pr:35] → [#35](url), [commit:a1b2c3d] → [a1b2c3d](url)."""
    def repl(m):
        ref = m.group(1)
        obj = raw.find(ref)
        kind, _, rest = ref.partition(":")
        alias, _, key = rest.rpartition("/")
        prefix = f"{alias}" if alias else ""
        if kind == "commit":
            label = f"{prefix}@{key}" if alias else key
        elif kind == "run":
            label = f"{prefix} run #{key}".strip()
        else:
            label = f"{prefix}#{key}"
        return f"[{label}](<{obj.url}>)" if obj is not None and getattr(obj, "url", "") else f"`{ref}`"
    return REF_RE.sub(repl, text)


def compact_refs(text: str, keep: int = 3) -> str:
    """한 줄에 근거 링크가 너무 많으면 앞의 몇 개만 남기고 '외 N개'로 줄인다 (읽기 쉽게)."""
    refs = list(REF_RE.finditer(text))
    if len(refs) <= keep:
        return text
    head = text[:refs[keep].start()].rstrip()
    tail = text[refs[-1].end():]
    return f"{head} 외 {len(refs) - keep}개{tail}"


def space_refs(text: str) -> str:
    """붙어 있는 근거 표시 사이에 공백을 넣어 링크가 한 덩어리로 보이지 않게 한다."""
    return re.sub(r"\]\[(?=(?:commit|pr|issue|run):)", "] [", text)


def render_report(report: Report, raw: RawActivity, warnings: list[str] | None = None) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True,
                      keep_trailing_newline=True)
    env.filters["links"] = lambda s: link_refs(space_refs(compact_refs(s)), raw)
    env.filters["refs"] = lambda refs: link_refs(" ".join(f"[{r}]" for r in refs), raw)
    return env.get_template("report.md.j2").render(
        r=report, icon=SEV_ICON, name=lambda k: report.display_names.get(k, k or "미지정"),
        warnings=warnings or [], repo=raw.repo)
