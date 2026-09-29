"""비밀값 읽기.

환경 변수를 먼저 보고, 없으면 GitHub Actions 에서 넘겨준 ``SECRETS_JSON``(= ``toJSON(secrets)``)에서 찾는다.
그래서 config.yaml 에 채널을 추가해도 워크플로 파일을 고칠 필요가 없다.
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
