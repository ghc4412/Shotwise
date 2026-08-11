"""
认证 API 路由

提供 OAuth2 登录、GitHub OAuth 登录和 token 验证接口。
"""

import logging
import os
import secrets
import time
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from lib.i18n import Translator
from server.auth import (
    CurrentUser,
    check_credentials,
    create_token,
    is_auth_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 公开端点：拿到 token 之前必须可达，注册时不挂 Bearer 依赖。
public_router = APIRouter()


# ==================== 响应模型 ====================


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    # 登录用户的角色（admin/user），取自 users 表；关闭认证时固定为 admin
    role: str = "admin"


class VerifyResponse(BaseModel):
    valid: bool
    username: str
    role: str = "admin"


class AuthStatusResponse(BaseModel):
    enabled: bool


# ==================== 路由 ====================


@public_router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status():
    """暴露 ``AUTH_ENABLED`` 状态供前端 bootstrap 判断是否需要登录拦截。

    前端 ``auth-store.initialize()`` 在 localStorage 无 token 时调用本接口：
    ``enabled=false`` 时跳过登录页直接进主界面；``enabled=true`` 时保留原
    登录链路。本接口本身**不要求认证**——一个 boolean 比 401 探针更直观，
    且实际"是否需要登录"通过 401/200 也能从外部观察到，因此不增量泄露。
    """
    return AuthStatusResponse(enabled=is_auth_enabled())


@public_router.post("/auth/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    _t: Translator,
):
    """用户登录

    使用 OAuth2 标准表单格式验证凭据，成功返回 access_token 和登录用户角色。
    ``AUTH_ENABLED=false`` 时跳过凭据校验，直接签发 token，让前端
    LoginPage 即便被打开也能正常跳转主界面。
    """
    if is_auth_enabled() and not check_credentials(form_data.username, form_data.password):
        logger.warning("登录失败: 用户名或密码错误 (用户: %s)", form_data.username)
        raise HTTPException(
            status_code=401,
            detail=_t("unauthorized"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_token(form_data.username)
    logger.info("用户登录成功: %s", form_data.username)
    return TokenResponse(access_token=token, token_type="bearer", role=await _resolve_role(form_data.username))


async def _resolve_role(username: str) -> str:
    """从 users 表解析登录用户的角色；记录缺失或查库失败时按普通用户处理（fail-closed）。"""
    if not is_auth_enabled():
        return "admin"
    try:
        from lib.db import async_session_factory
        from lib.db.repositories.user_repository import UserRepository

        async with async_session_factory() as session:
            user = await UserRepository(session).get_by_username(username)
        if user is not None:
            return user["role"]
    except Exception:
        logger.exception("读取用户角色失败（登录用户名: %s），按普通用户处理", username)
    return "user"


@router.post("/auth/logout", status_code=204)
async def logout(current_user: CurrentUser):
    """登出

    JWT 无状态，token 由前端本地清除即可失效；本端点仅记录登出日志，
    供审计与未来 token 黑名单扩展使用。
    """
    logger.info("用户登出: %s", current_user.sub)
    return None


@router.get("/auth/verify", response_model=VerifyResponse)
async def verify(
    current_user: CurrentUser,
):
    """验证 token 有效性

    使用 OAuth2 Bearer token 依赖自动提取和验证 token，返回用户名与角色。
    """
    return VerifyResponse(valid=True, username=current_user.sub, role=current_user.role)


# ==================== GitHub OAuth 登录 ====================
#
# 未配置 GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET 时，config 端点返回
# configured=false，前端隐藏 GitHub 登录入口；authorize/callback 直接
# 返回 409，避免半配置状态产生不可用链路。

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_API_URL = "https://api.github.com/user"
_OAUTH_STATE_TTL_SECONDS = 300  # 5 分钟
_GITHUB_OAUTH_TIMEOUT_SECONDS = 10

# state -> 过期时间戳（登录页跳转授权、回调校验，防 CSRF 与重放）
_oauth_states: dict[str, float] = {}


def github_oauth_configured() -> bool:
    return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))


def _github_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return f"{_GITHUB_AUTHORIZE_URL}?client_id={client_id}&redirect_uri={redirect_uri}&state={state}&scope=read:user"


async def _exchange_code_for_token(code: str) -> str:
    """用授权 code 换取 GitHub access token（可 patch 供测试）。"""
    async with httpx.AsyncClient(timeout=_GITHUB_OAUTH_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            _GITHUB_TOKEN_URL,
            data={
                "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
                "client_secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise ValueError(f"GitHub token exchange failed: {payload.get('error', 'unknown')}")
    return token


async def _fetch_github_user(access_token: str) -> dict:
    """用 access token 获取 GitHub 用户信息（可 patch 供测试）。"""
    async with httpx.AsyncClient(timeout=_GITHUB_OAUTH_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            _GITHUB_USER_API_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "Shotwise",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _oauth_error_redirect(code: str) -> RedirectResponse:
    """登录失败时跳回登录页并携带错误标记（前端读取 hash 展示）。"""
    base = os.environ.get("PUBLIC_FRONTEND_URL", "")
    return RedirectResponse(url=f"{base}/login#oauth_error={code}", status_code=302)


def _oauth_state_store() -> dict[str, float]:
    """清理过期的 state 后返回存储，便于测试重置。"""
    now = time.monotonic()
    expired = [k for k, v in _oauth_states.items() if v < now]
    for k in expired:
        _oauth_states.pop(k, None)
    return _oauth_states


@public_router.get("/auth/github/config")
async def github_config() -> dict:
    """返回 GitHub 登录是否已配置，供前端决定是否渲染登录入口。"""
    return {"configured": github_oauth_configured()}


@public_router.get("/auth/github/authorize")
async def github_authorize(request: Request) -> RedirectResponse:
    """发起 GitHub OAuth 授权：生成 state 并重定向到 GitHub 授权页。"""
    if not github_oauth_configured():
        raise HTTPException(status_code=409, detail="GitHub OAuth 未配置")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.monotonic() + _OAUTH_STATE_TTL_SECONDS

    redirect_uri = os.environ.get("GITHUB_REDIRECT_URI") or str(request.url_for("github_callback"))
    return RedirectResponse(
        url=_github_authorize_url(os.environ["GITHUB_CLIENT_ID"], redirect_uri, state),
        status_code=302,
    )


@public_router.get("/auth/github/callback")
async def github_callback(request: Request, code: str, state: str) -> RedirectResponse:
    """GitHub 授权回调：校验 state、换 token、取用户、注册/登录、签发 JWT 回跳前端。

    成功重定向到 ``/app/projects#token=<jwt>``；失败重定向到
    ``/login#oauth_error=<code>``，由前端登录页展示。
    """
    if not github_oauth_configured():
        raise HTTPException(status_code=409, detail="GitHub OAuth 未配置")

    store = _oauth_state_store()
    expires_at = store.pop(state, None)
    if expires_at is None or expires_at < time.monotonic():
        logger.warning("GitHub OAuth state 无效或已过期")
        return _oauth_error_redirect("invalid_state")

    try:
        access_token = await _exchange_code_for_token(code)
        gh_user = await _fetch_github_user(access_token)
    except Exception:
        logger.exception("GitHub OAuth 交换/取用户失败")
        return _oauth_error_redirect("auth_failed")

    github_id = str(gh_user.get("id", "")).strip()
    username = str(gh_user.get("login", "")).strip()
    if not github_id or not username:
        logger.warning("GitHub 用户信息缺少 id/login")
        return _oauth_error_redirect("auth_failed")

    try:
        from lib.db import async_session_factory
        from lib.db.repositories.user_repository import UserRepository

        async with async_session_factory() as session:
            async with session.begin():
                user = await UserRepository(session).get_or_create_github_user(github_id, username)
    except ValueError:
        logger.warning("GitHub 用户名不可用: %s", username)
        return _oauth_error_redirect("username_taken")
    except Exception:
        logger.exception("GitHub 用户落库失败（github_id=%s）", github_id)
        return _oauth_error_redirect("auth_failed")

    token = create_token(user["username"])
    logger.info("GitHub 用户登录成功: %s", user["username"])
    # 跳回前端：PUBLIC_FRONTEND_URL 用于前后端分离部署（dev 场景前端在 5173），
    # 未设置时相对跳转（同域部署，浏览器沿用当前 origin）。
    frontend_base = os.environ.get("PUBLIC_FRONTEND_URL", "")
    return RedirectResponse(url=f"{frontend_base}/app/projects#token={token}", status_code=302)
