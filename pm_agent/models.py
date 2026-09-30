"""데이터 모델 (docs/DATA_SPEC.md 3·6장, docs/AGENTS.md 2장)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Severity = Literal["critical", "high", "medium", "low"]
Area = Literal["pr", "ci", "issue"]
SEVERITY_ORDER: list[str] = ["low", "medium", "high", "critical"]

# ref 형식: "<kind>:<key>" 또는 여러 저장소일 때 "<kind>:<alias>/<key>" (예: pr:35, pr:web/35, commit:api/a1b2c3d)
REF_RE = re.compile(r"\[((?:commit|pr|issue|run):(?:[A-Za-z0-9_.-]+/)?[0-9a-f]+)\]")


def make_ref(kind: str, repo: str, key: object) -> str:
    return f"{kind}:{repo}/{key}" if repo else f"{kind}:{key}"


# ---------------------------------------------------------------- 수집 데이터
class Commit(BaseModel):
    sha: str
    author: str | None
    message: str
    committed_at: datetime
    url: str
    issue_refs: list[int] = Field(default_factory=list)
    repo: str = ""            # 여러 저장소일 때 저장소 별칭

    @property
    def ref(self) -> str:
        return make_ref("commit", self.repo, self.sha)


class Review(BaseModel):
    reviewer: str
    state: Literal["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"]
    submitted_at: datetime


class PullRequest(BaseModel):
    number: int
    title: str
    author: str
    state: Literal["open", "closed", "merged"]
    draft: bool = False
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None
    requested_reviewers: list[str] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    commits: list[Commit] = Field(default_factory=list)
    closes_issues: list[int] = Field(default_factory=list)
    url: str
    repo: str = ""

    @property
    def ref(self) -> str:
        return make_ref("pr", self.repo, self.number)


class Issue(BaseModel):
    number: int
    title: str
    state: Literal["open", "closed"]
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    assigned_at: datetime | None = None          # 마지막 assigned 이벤트 시각
    last_linked_activity: datetime | None = None  # 이 이슈를 참조한 커밋/PR의 마지막 활동
    url: str
    repo: str = ""

    @property
    def ref(self) -> str:
        return make_ref("issue", self.repo, self.number)


class CIJob(BaseModel):
    job_id: int
    name: str
    conclusion: str | None = None
    failed_step: str | None = None
    failed_tests: list[str] = Field(default_factory=list)
    log_tail: str = ""


class CIRun(BaseModel):
    run_id: int
    run_number: int
    workflow: str
    branch: str
    head_sha: str
    event: str = "push"
    # GitHub 값: success, failure, cancelled, skipped, timed_out, action_required, neutral, stale,
    # startup_failure 등. 규칙은 success/failure 만 사용하므로 나머지는 그대로 받아 둔다.
    conclusion: str | None = None
    created_at: datetime
    actor: str | None = None
    jobs: list[CIJob] = Field(default_factory=list)
    url: str
    repo: str = ""

    @property
    def ref(self) -> str:
        return make_ref("run", self.repo, self.run_number)

    @property
    def failed_tests(self) -> list[str]:
        return [t for j in self.jobs for t in j.failed_tests]


class RawActivity(BaseModel):
    repo: str                                  # 표시용 이름 (저장소 하나면 owner/name)
    default_branch: str = "main"
    default_branches: dict[str, str] = Field(default_factory=dict)   # 별칭 → 기본 브랜치
    since: datetime
    until: datetime
    commits: list[Commit] = Field(default_factory=list)
    pull_requests: list[PullRequest] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    open_assigned: dict[str, list[Issue]] = Field(default_factory=dict)
    open_unassigned_bugs: list[Issue] = Field(default_factory=list)
    ci_runs: list[CIRun] = Field(default_factory=list)
    unmapped_commits: int = 0

    def in_window(self, t: datetime | None) -> bool:
        return t is not None and self.since <= t <= self.until

    def branch_of(self, repo_alias: str) -> str:
        return self.default_branches.get(repo_alias, self.default_branch)

    def all_commits(self) -> list[Commit]:
        seen: dict[str, Commit] = {}
        for c in self.commits:
            seen.setdefault(c.ref, c)
        for p in self.pull_requests:
            for c in p.commits:
                seen.setdefault(c.ref, c)
        return list(seen.values())

    def all_issues(self) -> list[Issue]:
        seen: dict[str, Issue] = {}
        for i in self.issues + self.open_unassigned_bugs:
            seen.setdefault(i.ref, i)
        for lst in self.open_assigned.values():
            for i in lst:
                seen.setdefault(i.ref, i)
        return list(seen.values())

    def index(self) -> dict[str, object]:
        idx: dict[str, object] = {}
        for obj in [*self.all_commits(), *self.pull_requests, *self.all_issues(), *self.ci_runs]:
            idx.setdefault(obj.ref, obj)
        return idx

    def ref_universe(self) -> set[str]:
        return set(self.index())

    def find(self, ref: str):
        return self.index().get(ref)


# ---------------------------------------------------------------- 근거 데이터
EvidenceKind = Literal[
    "commit", "pr_merged", "pr_opened", "review", "issue_closed",
    "issue_assigned", "review_requested", "draft_pr",
]


KIND_LABEL: dict[str, str] = {
    "commit": "커밋", "pr_merged": "PR 머지", "pr_opened": "PR 생성", "review": "리뷰",
    "issue_closed": "이슈 해결", "issue_assigned": "담당 이슈",
    "review_requested": "리뷰 요청 받음", "draft_pr": "작업 중(Draft)",
}


class EvidenceItem(BaseModel):
    ref: str
    kind: EvidenceKind
    title: str
    url: str

    @field_validator("title")
    @classmethod
    def _no_brackets(cls, v: str) -> str:
        # 커밋 메시지·제목은 외부 입력: "[pr:999]" 같은 근거 표기를 흉내 내지 못하게 대괄호를 바꾼다
        return v.replace("[", "(").replace("]", ")")


class MemberDigest(BaseModel):
    member: str
    display: str
    yesterday: list[EvidenceItem] = Field(default_factory=list)
    today: list[EvidenceItem] = Field(default_factory=list)


# ---------------------------------------------------------------- 분석 결과
class RiskCandidate(BaseModel):
    id: str
    rule_id: str
    area: Area
    severity: Severity
    refs: list[str]
    owner: str | None = None
    facts: dict = Field(default_factory=dict)


class FindingDraft(BaseModel):
    """LLM이 채우는 Finding (구조화 출력 스키마)."""
    candidate_id: str = Field(description="분석 대상 후보의 id (예: c1)")
    severity: Severity = Field(description="규칙이 정한 심각도에서 최대 한 단계만 조정")
    title: str = Field(description="한 줄 요약, 60자 이내")
    explanation: str = Field(description="원인 추정과 영향, 2문장 이내")
    suggested_action: str = Field(description="누가 무엇을 하면 되는지, 1문장")


class AnalysisResult(BaseModel):
    findings: list[FindingDraft]


class CIAnalysisResult(AnalysisResult):
    handoff_to_diagnoser: bool = Field(
        description="반복 실패나 flaky 테스트의 원인 진단이 필요하면 true")
    handoff_reason: str = ""


class Finding(BaseModel):
    candidate_id: str
    rule_id: str
    area: Area
    severity: Severity
    title: str
    explanation: str
    suggested_action: str
    owner: str | None = None
    refs: list[str]


class Diagnosis(BaseModel):
    test: str = Field(description="진단한 테스트 이름")
    pattern: Literal["flaky", "regression", "env", "unknown"]
    hypothesis: str = Field(description="원인 가설, 2문장 이내")
    evidence_lines: list[str] = Field(description="입력 로그에서 글자 그대로 인용한 줄, 최대 5줄")
    suspect_commit: str | None = Field(default=None, description='"commit:<sha>" 형식 또는 null')
    next_step: str


class MemberSection(BaseModel):
    member: str
    yesterday: list[str] = Field(description='각 줄 끝에 근거 ref, 예: "로그인 API PR 머지 [pr:35]"')
    today: list[str]
    note: str | None = None


BARE_REF_RE = re.compile(r"^\[?((?:commit|pr|issue|run):(?:[A-Za-z0-9_.-]+/)?[0-9a-f]+)\]?$")


class DraftLine(BaseModel):
    """LLM 이 쓰는 한 줄: 문장과 근거를 따로 받는다.
    (실제 LLM 실행에서 '문장 끝에 [ref]' 형식을 헷갈려 ref 만 적어 보내는 문제가 있어 분리)"""
    text: str = Field(description="한국어 한 문장. 근거 ref 는 여기에 쓰지 말고 refs 에 넣을 것")
    refs: list[str] = Field(description='이 문장의 근거 ref 목록. EVIDENCE 의 ref 값을 그대로 복사, 예: ["pr:35"]')

    @model_validator(mode="before")
    @classmethod
    def _from_str(cls, v):
        if isinstance(v, str):
            bare = BARE_REF_RE.match(v.strip())
            if bare:                                   # "pr:3" 처럼 근거만 온 경우
                return {"text": "", "refs": [bare.group(1)]}
            return {"text": REF_RE.sub("", v).strip(), "refs": REF_RE.findall(v)}
        return v

    def render(self) -> str:
        refs = [r.strip().strip("[]") for r in self.refs]
        return f"{self.text.strip()} {''.join(f'[{r}]' for r in refs)}".strip()


class DraftMember(BaseModel):
    member: str = Field(description="EVIDENCE 의 member 값(영문 key)을 그대로")
    yesterday: list[DraftLine] = Field(default_factory=list, description="yesterday 근거만 사용")
    today: list[DraftLine] = Field(default_factory=list, description="today 근거만 사용")
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_section(cls, v):
        return v.model_dump() if isinstance(v, BaseModel) else v


class SummaryDraft(BaseModel):
    members: list[DraftMember]
    headline: str = Field(description="오늘의 한 줄 요약, 80자 이내")


class Report(BaseModel):
    date: str
    headline: str
    risks: list[Finding]
    diagnosis: Diagnosis | None = None
    members: list[MemberSection]
    display_names: dict[str, str]
    stats: dict[str, int | float | str]
    notice: str | None = None
