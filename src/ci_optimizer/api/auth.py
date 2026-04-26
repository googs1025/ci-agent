"""API key authentication dependency."""
# ── 架构角色 ──────────────────────────────────────────────────────────────────
# 本文件提供 FastAPI 依赖注入函数 verify_api_key，被所有需要鉴权的路由通过
# dependencies=[Depends(verify_api_key)] 引用。
# 设计决策：未设置 CI_AGENT_API_KEY 时跳过鉴权，便于本地开发零配置启动；
# 生产部署时通过环境变量注入密钥即可启用。

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# auto_error=False：让我们自己控制 401 响应，而不是 FastAPI 默认的 403
_security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Verify the Bearer token matches CI_AGENT_API_KEY.

    When CI_AGENT_API_KEY is not set, authentication is skipped entirely
    (backward-compatible for local development).
    校验逻辑：读取环境变量 → 未配置则放行 → 配置了则要求 Bearer token 完全匹配。
    """
    api_key = os.getenv("CI_AGENT_API_KEY")
    if not api_key:
        return  # no key configured — skip auth
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
