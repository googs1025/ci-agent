"""API key authentication dependency."""

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Verify the Bearer token matches CI_AGENT_API_KEY.

    When CI_AGENT_API_KEY is not set, authentication is skipped entirely
    (backward-compatible for local development).
    """
    api_key = os.getenv("CI_AGENT_API_KEY")
    if not api_key:
        return  # no key configured — skip auth
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
