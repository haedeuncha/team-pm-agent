"""근무일 판단: 주말·공휴일(기본 한국)·회사 휴일에는 정기 실행을 건너뛴다."""
from __future__ import annotations

from datetime import date, datetime

from .config import Config

WEEKDAY_KO = "월화수목금토일"


def holiday_name(d: date, cfg: Config) -> str | None:
    if d in cfg.schedule.extra_holidays:
        return "회사 휴일"
    if not cfg.schedule.skip_holidays:
        return None
    try:
        import holidays
    except ImportError:  # pragma: no cover - requirements 에 포함
        return None
    lang = "ko" if cfg.schedule.holiday_country == "KR" else None   # 시스템 언어와 무관하게 한국어 이름
    cal = holidays.country_holidays(cfg.schedule.holiday_country, years=d.year, language=lang)
    return cal.get(d)


def skip_reason(now: datetime, cfg: Config) -> str | None:
    """정기 실행을 건너뛸 이유. 근무일이면 None."""
    local = now.astimezone(cfg.tz).date()
    if cfg.schedule.skip_weekends and local.weekday() >= 5:
        return f"{local} ({WEEKDAY_KO[local.weekday()]}) 주말"
    name = holiday_name(local, cfg)
    if name:
        return f"{local} {name}"
    return None
