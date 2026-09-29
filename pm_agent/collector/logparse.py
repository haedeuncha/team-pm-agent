"""CI 로그에서 실패한 테스트 이름 추출 (docs/DATA_SPEC.md 4장)."""
from __future__ import annotations

import re

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TS_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")

PATTERNS: dict[str, re.Pattern[str]] = {
    "pytest": re.compile(r"^FAILED (\S+::\S+)"),
    "jest": re.compile(r"^\s*● (.+? › .+)$"),
    "junit": re.compile(r"^(\S+ > \S+) FAILED$"),
}


def clean_log(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = ANSI_RE.sub("", raw)
        line = TS_PREFIX_RE.sub("", line)
        lines.append(line.rstrip())
    return lines


def tail(text: str, n: int = 200) -> str:
    return "\n".join(clean_log(text)[-n:])


def failed_tests(text: str, pattern: str = "pytest") -> list[str]:
    rx = PATTERNS.get(pattern)
    if rx is None:
        raise ValueError(f"지원하지 않는 test_log_pattern: {pattern}")
    found: list[str] = []
    for line in clean_log(text):
        m = rx.search(line)
        if m and m.group(1) not in found:
            found.append(m.group(1).strip())
    return found
