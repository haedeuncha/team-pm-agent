"""config.yaml 로더 (docs/DATA_SPEC.md 5장)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Member(BaseModel):
    display: str
    github: str
    emails: list[str] = Field(default_factory=list)


class Thresholds(BaseModel):
    pr_stale_hours: int = 48
    pr_abandoned_days: int = 5
    issue_blocked_days: int = 3
    ci_repeat_window: int = 5
    ci_repeat_min_failures: int = 3
    ci_recent_runs: int = 20


class LLMConfig(BaseModel):
    provider: str = "fake"      # fake | openai | anthropic
    model: str | None = None
    temperature: float = 0.0


class Config(BaseModel):
    team_repo: str
    timezone: str = "Asia/Seoul"
    leader: str
    approval_deadline_kst: str = "12:00"
    members: dict[str, Member]
    bots: list[str] = Field(default_factory=list)
    test_log_pattern: str = "pytest"
    thresholds: Thresholds = Field(default_factory=Thresholds)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    max_hops: int = 6

    # ---- 매핑 도우미
    def member_by_login(self, login: str | None) -> str | None:
        if not login:
            return None
        for key, m in self.members.items():
            if m.github.lower() == login.lower():
                return key
        return None

    def member_by_email(self, email: str | None) -> str | None:
        if not email:
            return None
        for key, m in self.members.items():
            if email.lower() in (e.lower() for e in m.emails):
                return key
        return None

    def display(self, key: str | None) -> str:
        if key and key in self.members:
            return self.members[key].display
        return key or "미지정"


def load_config(path: str | Path = "config.yaml") -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Config.model_validate(data)
