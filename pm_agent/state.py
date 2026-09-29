"""그래프 State (docs/AGENTS.md 2장)."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from .models import (Diagnosis, Finding, MemberDigest, RawActivity, Report,
                     RiskCandidate)


class PMState(TypedDict, total=False):
    raw: RawActivity
    candidates: list[RiskCandidate]
    digests: dict[str, MemberDigest]
    active_areas: list[str]                           # 기간 안에 변화가 있던 영역
    done_areas: Annotated[list[str], operator.add]
    findings: Annotated[list[Finding], operator.add]
    handoff_payload: dict | None
    diagnosis: Diagnosis | None
    report: Report | None
    report_md: str
    validation_errors: list[str]
    attempts: int
    hops: int
    warnings: Annotated[list[str], operator.add]
    trace: Annotated[list[str], operator.add]         # 실행한 노드 순서 (TC-GRAPH)
