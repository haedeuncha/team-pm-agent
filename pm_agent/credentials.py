"""비밀값 읽기.

환경 변수를 먼저 보고, 없으면 ``SECRETS_JSON``(JSON 문자열, Docker·서버 실행 시 선택)에서 찾는다.
기본 워크플로는 보안상 필요한 비밀값만 환경 변수로 넘긴다 (``toJSON(secrets)`` 는 GitHub 가 악성 패턴으로 차단).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _secrets_json() -> dict:
    raw = os.getenv("SECRETS_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def get_secret(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    if value:
        return value
    value = _secrets_json().get(name)
    return value or None


def reset_cache() -> None:
    _secrets_json.cache_clear()
