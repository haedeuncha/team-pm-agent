"""수집 기간 계산 (docs/DATA_SPEC.md 1장)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def parse_since(value: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([dh])", value.strip())
    if not m:
        raise ValueError(f"since 형식은 1d, 7d, 12h 같은 값이어야 합니다: {value!r}")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(days=n) if unit == "d" else timedelta(hours=n)


def compute_window(now: datetime, *, last_success: datetime | None = None,
                   since_opt: str | None = None) -> tuple[datetime, datetime]:
    """(since, until) 을 UTC 기준으로 반환한다.

    - since_opt 가 주어지면 (수동 실행) now - since_opt
    - 직전 성공 실행 시각이 있으면 그 시각부터
    - 없으면 24시간 전 (KST 월요일이면 72시간 전)
    """
    if since_opt:
        return now - parse_since(since_opt), now
    if last_success is not None and last_success < now:
        return last_success, now
    hours = 72 if now.astimezone(KST).weekday() == 0 else 24
    return now - timedelta(hours=hours), now
