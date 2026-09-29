"""TC-PUB: 발송, 승인 만료."""
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from pm_agent.publish import is_expired, send, split_message


def test_pub01_split_under_limit_by_section():
    md = "# 제목\n\n" + "\n\n".join(f"## 섹션{i}\n" + "\n".join(f"- 줄 {i}-{j} " + "가" * 40 for j in range(25))
                                  for i in range(4))
    chunks = split_message(md)
    assert len(md) > 4000 and len(chunks) >= 3
    assert all(len(c) <= 1900 for c in chunks)
    assert all(c.startswith(("## ", "- ")) for c in chunks[1:])   # 섹션 또는 줄 경계에서 자름


def test_pub01b_short_report_single_message():
    assert split_message("# a\n\n## b\n- c") == ["# a\n\n## b\n- c"]


def test_pub02_retry_on_429():
    calls, waits = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 0.5})
        return httpx.Response(204)

    assert send(["hi"], "https://discord.test/webhook", transport=httpx.MockTransport(handler),
                sleep=waits.append) == 1
    assert waits == [0.5]


KST = ZoneInfo("Asia/Seoul")


def kst(day, h, m=0):
    return datetime(2026, 9 if day <= 30 else 10, day if day <= 30 else day - 30, h, m, tzinfo=KST)


def test_approval_expires_after_deadline():
    gen = kst(30, 8, 7)
    assert not is_expired(gen, "12:00", kst(30, 11, 59))
    assert is_expired(gen, "12:00", kst(30, 12, 1))


def test_manual_run_after_deadline_valid_until_next_day():
    gen = kst(30, 15, 0)
    assert not is_expired(gen, "12:00", kst(30, 18, 0))
    assert not is_expired(gen, "12:00", kst(31, 11, 59))
    assert is_expired(gen, "12:00", kst(31, 12, 1))
