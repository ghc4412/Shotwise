"""
登录 API 路由测试

测试 server.routers.auth 中的登录和 token 验证路由。
"""

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.auth as auth_module
from server.routers import auth as auth_router
from tests.auth_deps import AUTH_DEPENDENCIES

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    """创建测试客户端，设置固定的认证环境变量。

    ``_payload_to_user`` / ``_resolve_role`` 会查 users 表解析角色，这里把
    ``UserRepository.get_by_username`` mock 成固定 admin 用户，避免依赖真实
    DB；断言 401/403 的用例不受影响（依赖注入在认证通过后执行）。
    """
    from lib.db.repositories.user_repository import UserRepository

    async def _fake_get_by_username(self, username: str) -> dict:
        return {"id": "default", "username": username, "role": "admin", "is_active": True}

    auth_module._cached_token_secret = None
    auth_module._cached_password_hash = None
    with (
        patch.dict(
            os.environ,
            {
                "AUTH_USERNAME": "testuser",
                "AUTH_PASSWORD": "testpass",
                "AUTH_TOKEN_SECRET": "test-router-secret-key-at-least-32-bytes-long",
                # uv run 会把开发 .env 注入测试进程；GitHub 相关键必须显式清空，
                # 否则"未配置"类断言会受开发者本地 .env 污染。
                "GITHUB_CLIENT_ID": "",
                "GITHUB_CLIENT_SECRET": "",
                "GITHUB_REDIRECT_URI": "",
                "PUBLIC_FRONTEND_URL": "",
            },
        ),
        patch.object(UserRepository, "get_by_username", _fake_get_by_username),
    ):
        app = FastAPI()
        app.include_router(auth_router.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
        app.include_router(auth_router.public_router, prefix="/api/v1")
        with TestClient(app) as c:
            yield c


class TestLoginRoute:
    def test_login_success(self, client):
        """正确凭据返回 200 + access_token + role"""
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0
        assert data["role"] == "admin"

    def test_login_wrong_password(self, client):
        """错误密码返回 401"""
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "wrongpass"},
        )
        assert resp.status_code == 401

    def test_login_wrong_username(self, client):
        """错误用户名返回 401"""
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": "wronguser", "password": "testpass"},
        )
        assert resp.status_code == 401


class TestVerifyRoute:
    def test_verify_valid_token(self, client):
        """有效 token 验证通过，返回用户名与角色"""
        login_resp = client.post(
            "/api/v1/auth/token",
            data={"username": "testuser", "password": "testpass"},
        )
        token = login_resp.json()["access_token"]

        resp = client.get(
            "/api/v1/auth/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["username"] == "testuser"
        assert data["role"] == "admin"

    def test_verify_no_token(self, client):
        """缺少 token 返回 401"""
        resp = client.get("/api/v1/auth/verify")
        assert resp.status_code == 401

    def test_verify_invalid_token(self, client):
        """无效 token 返回 401"""
        resp = client.get(
            "/api/v1/auth/verify",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_verify_returns_role_from_user(self, client):
        """verify 的角色取自当前认证用户的角色，而非硬编码 admin"""
        from server.auth import get_current_user

        client.app.dependency_overrides[get_current_user] = lambda: auth_module.CurrentUserInfo(
            id="default", sub="testuser", role="user"
        )
        resp = client.get("/api/v1/auth/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["role"] == "user"


class TestLogoutRoute:
    def test_logout_returns_204(self, client):
        """登出端点返回 204（token 由前端本地清除）"""
        from server.auth import get_current_user

        client.app.dependency_overrides[get_current_user] = lambda: auth_module.CurrentUserInfo(
            id="default", sub="testuser", role="admin"
        )
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 204


# ==================== GitHub OAuth ====================


@pytest.fixture()
def github_env(monkeypatch):
    """配置 GitHub OAuth 环境变量（并清空 .env 注入的 PUBLIC_FRONTEND_URL，保证相对跳转断言）。"""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "gh-client-secret")
    monkeypatch.setenv("GITHUB_REDIRECT_URI", "")
    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "")
    yield
    auth_router._oauth_states.clear()


class TestGitHubConfig:
    def test_config_not_configured(self, client):
        resp = client.get("/api/v1/auth/github/config")
        assert resp.status_code == 200
        assert resp.json() == {"configured": False}

    def test_config_configured(self, client, github_env):
        resp = client.get("/api/v1/auth/github/config")
        assert resp.status_code == 200
        assert resp.json() == {"configured": True}


class TestGitHubAuthorize:
    def test_authorize_rejected_when_unconfigured(self, client):
        resp = client.get("/api/v1/auth/github/authorize", follow_redirects=False)
        assert resp.status_code == 409

    def test_authorize_redirects_to_github(self, client, github_env):
        resp = client.get("/api/v1/auth/github/authorize", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=gh-client-id" in location
        assert "state=" in location
        assert "redirect_uri=" in location
        # state 已登记（供回调校验）
        state = location.split("state=")[1].split("&")[0]
        assert state in auth_router._oauth_states


class TestGitHubCallback:
    def test_callback_rejects_bad_state(self, client, github_env):
        resp = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "abc", "state": "not-issued"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login#oauth_error=invalid_state"

    def test_callback_full_flow(self, client, github_env, monkeypatch):
        """授权回调成功：换 token、取用户、落库、签发 JWT 回跳前端。"""
        from lib.db.repositories.user_repository import UserRepository

        async def _fake_get_or_create_github_user(self, github_id: str, username: str) -> dict:
            return {"id": f"github-{github_id}", "username": username, "role": "user"}

        async def _fake_exchange(code: str) -> str:
            assert code == "auth-code"
            return "gh-access-token"

        async def _fake_fetch(token: str) -> dict:
            assert token == "gh-access-token"
            return {"id": 4242, "login": "octocat"}

        # 登记一个合法 state
        state = "issued-state"
        auth_router._oauth_states[state] = __import__("time").monotonic() + 300

        with (
            patch.object(auth_router, "_exchange_code_for_token", _fake_exchange),
            patch.object(auth_router, "_fetch_github_user", _fake_fetch),
            patch.object(UserRepository, "get_or_create_github_user", _fake_get_or_create_github_user),
        ):
            resp = client.get(
                "/api/v1/auth/github/callback",
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("/app/projects#token=")
        token = location.split("#token=")[1]
        # 签发的 token 应能通过 verify 验证且 sub=octocat
        payload = auth_module.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "octocat"
        # state 一次性消费
        assert state not in auth_router._oauth_states

    def test_callback_username_taken(self, client, github_env, monkeypatch):
        from lib.db.repositories.user_repository import UserRepository

        async def _fake_exchange(code: str) -> str:
            return "gh-access-token"

        async def _fake_fetch(token: str) -> dict:
            return {"id": 4243, "login": "admin"}

        async def _raise(self, github_id: str, username: str) -> dict:
            raise ValueError("GitHub username unavailable: admin")

        state = "issued-state-2"
        auth_router._oauth_states[state] = __import__("time").monotonic() + 300

        with (
            patch.object(auth_router, "_exchange_code_for_token", _fake_exchange),
            patch.object(auth_router, "_fetch_github_user", _fake_fetch),
            patch.object(UserRepository, "get_or_create_github_user", _raise),
        ):
            resp = client.get(
                "/api/v1/auth/github/callback",
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert resp.headers["location"] == "/login#oauth_error=username_taken"
