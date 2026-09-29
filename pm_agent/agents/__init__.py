"""에이전트 노드 모음 (docs/AGENTS.md)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def dumps(obj) -> str:
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        raise TypeError(type(o))
    return json.dumps(obj, ensure_ascii=False, indent=1, default=default)
