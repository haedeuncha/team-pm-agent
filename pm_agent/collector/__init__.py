from __future__ import annotations

import json
from pathlib import Path

from ..models import RawActivity


def load_fixture(path: str | Path) -> RawActivity:
    """녹화된 fixture(JSON) 를 RawActivity 로 읽는다 (NFR-07, 네트워크 없이 실행)."""
    return RawActivity.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
