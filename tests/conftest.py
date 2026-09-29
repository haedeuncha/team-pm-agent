from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pm_agent.collector import load_fixture  # noqa: E402
from pm_agent.config import load_config  # noqa: E402
from pm_agent.models import RawActivity  # noqa: E402

NOW = datetime(2026, 9, 29, 23, 7, tzinfo=timezone.utc)


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def fixture():
    return lambda name: load_fixture(ROOT / "fixtures" / f"{name}.json")


@pytest.fixture
def empty_raw():
    return RawActivity(repo="demo-team/campus-market", since=NOW - timedelta(hours=24), until=NOW)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)
