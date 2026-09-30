"""config.yaml 로더 (docs/DATA_SPEC.md 5장, docs/OPERATIONS.md)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, model_validator


class Member(BaseModel):
    display: str
    github: str
    emails: list[str] = Field(default_factory=list)


class RepoConfig(BaseModel):
    name: str                 # owner/repo
    alias: str = ""           # 저장소가 여러 개일 때 ref 구분용 짧은 이름 (예: web, api)


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
    price_per_1m_input: float = 0.0     # 비용 추정용 (USD / 100만 토큰)
    price_per_1m_output: float = 0.0


class ScheduleConfig(BaseModel):
    skip_weekends: bool = True
    skip_holidays: bool = True
    holiday_country: str = "KR"
    extra_holidays: list[date] = Field(default_factory=list)   # 창립기념일 등


class ChannelConfig(BaseModel):
    """발송 채널 하나. type 별로 쓰는 필드가 다르다 (pm_agent/notify)."""
    type: Literal["discord", "slack", "teams", "email"]
    enabled: bool = True
    name: str | None = None
    # webhook 계열 (discord / slack / teams)
    webhook_env: str | None = None
    test_webhook_env: str | None = None
    # email (Gmail 등 SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_ssl: bool = False                    # 465 포트면 true
    username_env: str = "SMTP_USERNAME"
    password_env: str = "SMTP_PASSWORD"
    from_addr: str | None = None             # 비우면 username
    to: list[str] = Field(default_factory=list)
    to_env: str | None = None                # 쉼표로 구분한 수신자 (public 저장소면 이쪽 권장)
    test_to_env: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.type


class StateConfig(BaseModel):
    backend: Literal["none", "local", "github"] = "none"
    path: str = ".pm-agent-state"            # local
    repo: str | None = None                  # github: 비우면 GITHUB_REPOSITORY
    branch: str = "pm-agent-state"           # github


class SecurityConfig(BaseModel):
    redact_secrets: bool = True
    extra_patterns: list[str] = Field(default_factory=list)   # 회사 고유 비밀 형식 (정규식)


class GitHubConfig(BaseModel):
    api_url: str | None = None               # GitHub Enterprise Server 면 https://ghe.example.com/api/v3


class Config(BaseModel):
    team_name: str = "team"
    repos: list[RepoConfig] = Field(default_factory=list)
    team_repo: str | None = None             # (하위 호환) 저장소 하나
    timezone: str = "Asia/Seoul"
    leader: str
    approval_deadline: str = "12:00"
    approval_deadline_kst: str | None = None  # (하위 호환)
    members: dict[str, Member]
    bots: list[str] = Field(default_factory=list)
    test_log_pattern: str = "pytest"
    ci_exclude_workflows: list[str] = Field(default_factory=list)   # CI 분석에서 뺄 워크플로 이름
    thresholds: Thresholds = Field(default_factory=Thresholds)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    channels: list[ChannelConfig] = Field(default_factory=lambda: [
        ChannelConfig(type="discord", webhook_env="DISCORD_WEBHOOK_URL",
                      test_webhook_env="DISCORD_WEBHOOK_URL_TEST")])
    alerts: list[ChannelConfig] = Field(default_factory=list)
    state: StateConfig = Field(default_factory=StateConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    max_hops: int = 6

    @model_validator(mode="after")
    def _compat(self) -> "Config":
        if not self.repos and self.team_repo:
            self.repos = [RepoConfig(name=self.team_repo)]
        if not self.repos:
            raise ValueError("repos(또는 team_repo) 를 하나 이상 지정하세요")
        if self.approval_deadline_kst:
            self.approval_deadline = self.approval_deadline_kst
        aliases = [r.alias for r in self.repos]
        if len(self.repos) > 1 and (not all(aliases) or len(set(aliases)) != len(aliases)):
            raise ValueError("저장소가 여러 개면 각 저장소에 서로 다른 alias 를 지정하세요")
        if self.leader not in self.members:
            raise ValueError(f"leader '{self.leader}' 가 members 에 없습니다")
        return self

    # ---- 편의
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def repo_label(self) -> str:
        return ", ".join(r.name for r in self.repos)

    def set_repos_from_env(self, value: str) -> None:
        """TEAM_REPO 환경 변수: 'owner/a' 또는 'web=owner/a,api=owner/b'."""
        items = [v.strip() for v in value.split(",") if v.strip()]
        repos = []
        for it in items:
            alias, _, name = it.rpartition("=")
            repos.append(RepoConfig(name=name, alias=alias))
        if len(repos) == 1 and len(self.repos) == 1:
            repos[0].alias = repos[0].alias or self.repos[0].alias
        self.repos = repos
        self._compat()

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
