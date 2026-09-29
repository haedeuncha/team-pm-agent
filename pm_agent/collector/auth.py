"""GitHub 인증: GitHub App 설치 토큰(권장) 또는 개인 토큰(PAT).

회사에서는 사람 계정에 묶인 PAT 대신 GitHub App 을 쓴다.
- 퇴사·권한 변경에 영향을 받지 않음
- 저장소 단위로 최소 권한(read-only) 부여, 토큰은 1시간마다 자동 만료
- 조직 관리자가 설치·회수를 관리

GitHub Actions 에서는 ``actions/create-github-app-token`` 이 토큰을 만들어 GH_READ_TOKEN 으로 넘긴다.
Docker·서버에서 직접 실행할 때는 아래 환경 변수로 이 모듈이 토큰을 발급한다.

  GH_APP_ID, GH_APP_PRIVATE_KEY(PEM 내용), GH_APP_INSTALLATION_ID(선택)
"""
from __future__ import annotations

import time

from ..credentials import get_secret


def app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    import jwt  # PyJWT[crypto]
    now = int(now or time.time())
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": str(app_id)}
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def installation_token(client_factory, app_id: str, private_key_pem: str,
                       owner_repo: str, installation_id: str | None = None) -> str:
    """App JWT → 설치 ID 조회(없으면 저장소로) → 설치 토큰."""
    app_client = client_factory(app_jwt(app_id, private_key_pem))
    if not installation_id:
        installation_id = str(app_client.get(f"/repos/{owner_repo}/installation")["id"])
    data = app_client.send("POST", f"/app/installations/{installation_id}/access_tokens", {})
    return data["token"]


def resolve_token(owner_repo: str, client_factory=None) -> tuple[str | None, str]:
    """(토큰, 방식) 을 돌려준다. GH_READ_TOKEN 이 있으면 그대로 쓴다."""
    token = get_secret("GH_READ_TOKEN")
    if token:
        return token, "token"
    app_id, key = get_secret("GH_APP_ID"), get_secret("GH_APP_PRIVATE_KEY")
    if app_id and key:
        if client_factory is None:
            from .github import GitHubClient
            client_factory = GitHubClient
        key = key.replace("\\n", "\n")
        return installation_token(client_factory, app_id, key, owner_repo,
                                  get_secret("GH_APP_INSTALLATION_ID")), "github-app"
    return None, "none"
