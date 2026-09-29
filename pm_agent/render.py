"""Report → Markdown (Jinja2). LLM 은 마크다운을 직접 만들지 않는다."""
from __future__ import annotations

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


def render_report(report: Report, raw: RawActivity, warnings: list[str] | None = None) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True,
                      keep_trailing_newline=True)
    env.filters["links"] = lambda s: link_refs(s, raw)
    env.filters["refs"] = lambda refs: link_refs(" ".join(f"[{r}]" for r in refs), raw)
    return env.get_template("report.md.j2").render(
        r=report, icon=SEV_ICON, name=lambda k: report.display_names.get(k, k or "미지정"),
        warnings=warnings or [], repo=raw.repo)
