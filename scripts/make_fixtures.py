"""가상 팀(campus-market) 시나리오 fixture 생성기 (docs/DATA_SPEC.md 7장).

팀원: 해든(haeden, 팀장·인증), 민수(minsu, 결제), 지우(jiwoo, 프론트), 서연(seoyeon, 채팅·알림)
실행: python scripts/make_fixtures.py  →  fixtures/*.json
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "demo-team/campus-market"
GH = f"https://github.com/{REPO}"
OUT = Path(__file__).resolve().parent.parent / "fixtures"

NOW = datetime(2026, 9, 29, 23, 7, tzinfo=timezone.utc)        # KST 9/30(수) 08:07
MON_NOW = datetime(2026, 10, 4, 23, 7, tzinfo=timezone.utc)    # KST 10/5(월) 08:07


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def h(self, hours: float) -> str:
        return iso(self.now - timedelta(hours=hours))


def commit(c: Clock, sha: str, author: str | None, msg: str, hours: float, refs=()):
    return {"sha": sha, "author": author, "message": msg, "committed_at": c.h(hours),
            "url": f"{GH}/commit/{sha}", "issue_refs": list(refs)}


def pr(c: Clock, n, title, author, state="open", created=10, updated=None, merged=None, draft=False,
       requested=(), reviews=(), commits=(), closes=()):
    return {"number": n, "title": title, "author": author, "state": state, "draft": draft,
            "created_at": c.h(created), "updated_at": c.h(updated if updated is not None else created),
            "merged_at": c.h(merged) if merged is not None else None,
            "requested_reviewers": list(requested),
            "reviews": [{"reviewer": r, "state": s, "submitted_at": c.h(t)} for r, s, t in reviews],
            "commits": list(commits), "closes_issues": list(closes), "url": f"{GH}/pull/{n}"}


def issue(c: Clock, n, title, state="open", labels=(), assignees=(), created=30, updated=None,
          closed=None, closed_by=None, assigned=None, linked=None):
    return {"number": n, "title": title, "state": state, "labels": list(labels), "assignees": list(assignees),
            "created_at": c.h(created), "updated_at": c.h(updated if updated is not None else created),
            "closed_at": c.h(closed) if closed is not None else None, "closed_by": closed_by,
            "assigned_at": c.h(assigned) if assigned is not None else None,
            "last_linked_activity": c.h(linked) if linked is not None else None,
            "url": f"{GH}/issues/{n}"}


def run(c: Clock, number, sha, conclusion, hours, branch="main", actor="haeden", jobs=()):
    return {"run_id": 9000 + number, "run_number": number, "workflow": "CI", "branch": branch,
            "head_sha": sha, "event": "push", "conclusion": conclusion, "created_at": c.h(hours),
            "actor": actor, "jobs": list(jobs), "url": f"{GH}/actions/runs/{9000 + number}"}


PYTEST_FAIL_LOG = """============================= test session starts ==============================
platform linux -- Python 3.12.6, pytest-8.3.3
collected 48 items

tests/test_auth.py ....F.....                                            [ 20%]
tests/test_chat.py ...........                                           [ 43%]
tests/test_market.py ...........................                         [100%]

=================================== FAILURES ===================================
_________________________________ test_refresh _________________________________

    def test_refresh(client, issued_token):
        time.sleep(1.2)
>       assert client.refresh(issued_token).status_code == 200
E       AssertionError: assert 401 == 200
E        +  where 401 = <Response [401]>.status_code

tests/test_auth.py:57: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  auth.service:service.py:88 token expired: exp=1759187231 now=1759187232
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_refresh - AssertionError: assert 401 == 200
========================= 1 failed, 47 passed in 6.21s =========================
Error: Process completed with exit code 1."""


def failing_job(job_id: int):
    return {"job_id": job_id, "name": "test (3.12)", "conclusion": "failure", "failed_step": "Run pytest",
            "failed_tests": ["tests/test_auth.py::test_refresh"], "log_tail": PYTEST_FAIL_LOG}


def assigned_base(c: Clock, extra_jiwoo=()):
    return {
        "haeden": [issue(c, 41, "리프레시 토큰 갱신 버그", labels=["bug"], assignees=["haeden"],
                         created=30, assigned=20, linked=5)],
        "minsu": [issue(c, 43, "결제 취소 API", labels=["feature"], assignees=["minsu"],
                        created=50, assigned=30, linked=10)],
        "jiwoo": [issue(c, 42, "상품 목록 무한 스크롤", labels=["feature"], assignees=["jiwoo"],
                        created=40, assigned=26, linked=3), *extra_jiwoo],
        "seoyeon": [issue(c, 44, "채팅 읽음 표시", labels=["feature"], assignees=["seoyeon"],
                          created=60, assigned=40, linked=8)],
    }


def raw(c: Clock, since_hours=24, **kw):
    base = {"repo": REPO, "default_branch": "main", "since": c.h(since_hours), "until": iso(c.now),
            "commits": [], "pull_requests": [], "issues": [], "open_assigned": {},
            "open_unassigned_bugs": [], "ci_runs": [], "unmapped_commits": 0}
    base.update(kw)
    return base


def green_history(c: Clock):
    return [run(c, 110 + i, f"0{i}aa{i}bb", "success", 120 - i * 10) for i in range(5)]


# ------------------------------------------------------------------ 시나리오
def normal_day():
    c = Clock(NOW)
    pr35_commits = [commit(c, "a1b2c3d", "haeden", "로그인 API 구현 (#40)", 30, [40]),
                    commit(c, "b2c3d4e", "haeden", "로그인 실패 응답 코드 정리 (#40)", 9, [40])]
    return raw(c,
        commits=[
            commit(c, "c3d4e5f", "haeden", "리프레시 토큰 만료 로그 추가 (#41)", 5, [41]),
            commit(c, "d4e5f6a", "jiwoo", "상품 카드 컴포넌트 분리 (#42)", 14, [42]),
            commit(c, "e5f6a7b", "jiwoo", "무한 스크롤 IntersectionObserver 적용 (#42)", 3, [42]),
            commit(c, "f6a7b8c", "seoyeon", "채팅 읽음 이벤트 스키마 추가 (#44)", 8, [44]),
            commit(c, "0a1b2c3", "minsu", "결제 취소 요청 DTO 정의 (#43)", 10, [43]),
        ],
        pull_requests=[
            pr(c, 35, "로그인 API 구현", "haeden", state="merged", created=40, updated=6, merged=6,
               reviews=[("minsu", "APPROVED", 8)], commits=pr35_commits, closes=[40]),
            pr(c, 36, "상품 목록 UI", "jiwoo", created=10, requested=["seoyeon"],
               commits=[commit(c, "1b2c3d4", "jiwoo", "상품 목록 화면 레이아웃", 11, [42])]),
            pr(c, 33, "채팅방 목록 API", "seoyeon", created=50, updated=12, requested=["haeden"],
               commits=[commit(c, "2c3d4e5", "seoyeon", "채팅방 목록 페이지네이션", 12)]),
        ],
        issues=[
            issue(c, 40, "로그인 API", state="closed", labels=["feature"], assignees=["haeden"],
                  created=100, updated=6, closed=6, closed_by="haeden"),
            issue(c, 46, "이미지 업로드 용량 제한", labels=["enhancement"], created=5),
        ],
        open_assigned=assigned_base(c),
        ci_runs=green_history(c) + [
            run(c, 120, "c3d4e5f", "success", 5),
            run(c, 121, "1b2c3d4", "success", 11, branch="feature/product-list", actor="jiwoo"),
            run(c, 122, "b2c3d4e", "success", 6),
        ],
    )


def risky_day():
    c = Clock(NOW)
    return raw(c,
        commits=[
            commit(c, "c3d4e5f", "haeden", "리프레시 토큰 만료 로그 추가 (#41)", 5, [41]),
            commit(c, "e5f6a7b", "jiwoo", "무한 스크롤 IntersectionObserver 적용 (#42)", 3, [42]),
            commit(c, "f6a7b8c", "seoyeon", "채팅 읽음 이벤트 스키마 추가 (#44)", 8, [44]),
        ],
        pull_requests=[
            pr(c, 37, "결제 모듈 리팩터링", "minsu", created=52, updated=20,
               commits=[commit(c, "3d4e5f6", "minsu", "PG사 어댑터 인터페이스 분리 (#43)", 20, [43])]),
            pr(c, 31, "푸시 알림 설정 화면", "seoyeon", created=216, updated=144,
               commits=[commit(c, "4e5f6a7", "seoyeon", "알림 설정 토글 UI", 150)]),
            pr(c, 39, "상품 상세 페이지", "jiwoo", draft=True, created=30, updated=4,
               commits=[commit(c, "5f6a7b8", "jiwoo", "상세 페이지 이미지 슬라이더", 4)]),
        ],
        issues=[
            issue(c, 45, "로그아웃 후에도 채팅 알림이 계속 옴", labels=["bug"], created=48, updated=12),
        ],
        open_assigned=assigned_base(c, extra_jiwoo=[
            issue(c, 38, "찜하기 기능", labels=["feature"], assignees=["jiwoo"], created=120, assigned=96)]),
        open_unassigned_bugs=[
            issue(c, 45, "로그아웃 후에도 채팅 알림이 계속 옴", labels=["bug"], created=48, updated=12)],
        ci_runs=green_history(c) + [run(c, 120, "c3d4e5f", "success", 5)],
    )


def ci_flaky():
    c = Clock(NOW)
    return raw(c,
        commits=[
            commit(c, "d4e5f6b", "haeden", "토큰 갱신 로직 수정 (#41)", 10, [41]),
            commit(c, "e5f6a7b", "jiwoo", "무한 스크롤 IntersectionObserver 적용 (#42)", 3, [42]),
        ],
        pull_requests=[
            pr(c, 38, "채팅 알림 구독 해제", "seoyeon", created=22, updated=18,
               reviews=[("haeden", "APPROVED", 17)], state="merged", merged=16,
               commits=[commit(c, "c333333", "seoyeon", "로그아웃 시 알림 구독 해제 (#44)", 21, [44])]),
        ],
        issues=[],
        open_assigned=assigned_base(c),
        ci_runs=[
            run(c, 139, "a0a0a0a", "success", 80),
            run(c, 140, "a111111", "success", 60),
            run(c, 141, "b222222", "failure", 40, jobs=[failing_job(1)]),
            run(c, 142, "c333333", "failure", 20, branch="feature/chat-unsubscribe", actor="seoyeon",
                jobs=[failing_job(2)]),
            run(c, 143, "d4e5f6b", "success", 10),
            run(c, 144, "d4e5f6b", "failure", 9, jobs=[failing_job(3)]),
        ],
    )


def quiet_day():
    c = Clock(NOW)
    return raw(c, open_assigned=assigned_base(c), ci_runs=green_history(c))


def monday():
    c = Clock(MON_NOW)
    return raw(c, since_hours=72,
        commits=[
            commit(c, "7a8b9c0", "minsu", "결제 취소 환불 금액 계산 (#43)", 70, [43]),
            commit(c, "8b9c0d1", "seoyeon", "채팅 읽음 표시 UI (#44)", 50, [44]),
            commit(c, "9c0d1e2", "haeden", "토큰 갱신 테스트 시간 고정 (#41)", 20, [41]),
        ],
        issues=[issue(c, 41, "리프레시 토큰 갱신 버그", state="closed", labels=["bug"], assignees=["haeden"],
                      created=150, closed=19, closed_by="haeden")],
        open_assigned={k: v for k, v in assigned_base(c).items() if k != "haeden"},
        ci_runs=[run(c, 150 + i, "9c0d1e2", "success", 60 - i * 10) for i in range(3)],
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, fn in [("normal_day", normal_day), ("risky_day", risky_day), ("ci_flaky", ci_flaky),
                     ("quiet_day", quiet_day), ("monday", monday)]:
        (OUT / f"{name}.json").write_text(json.dumps(fn(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"fixtures/{name}.json")


if __name__ == "__main__":
    main()
