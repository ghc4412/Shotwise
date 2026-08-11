"""
用户角色解析、默认用户同步与 admin 权限测试。

覆盖三件事：
1. ``UserRepository.ensure_default_user`` 的 upsert 语义
2. ``server.auth.ensure_default_user`` 启动同步（AUTH_USERNAME 驱动）
3. ``require_admin`` 依赖：非 admin 角色 403、admin 放行、管理端点生效
"""

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import server.auth as auth_module
from lib.db.base import Base
from lib.db.repositories.user_repository import UserRepository
from server.routers import api_keys
from tests.auth_deps import AUTH_DEPENDENCIES

pytestmark = pytest.mark.unit


class TestUserRepository:
    async def test_ensure_default_user_creates(self, async_session):
        """无记录时创建 id="default" 的用户。"""
        user = await UserRepository(async_session).ensure_default_user("alice")
        assert user["id"] == "default"
        assert user["username"] == "alice"
        assert user["role"] == "admin"
        assert user["is_active"] is True

    async def test_ensure_default_user_updates_username(self, async_session):
        """已存在时按 env 用户名原地更新，id 保持稳定。"""
        repo = UserRepository(async_session)
        await repo.ensure_default_user("alice")
        updated = await repo.ensure_default_user("bob")
        assert updated["id"] == "default"
        assert updated["username"] == "bob"
        assert updated["role"] == "admin"

        again = await repo.get_by_id("default")
        assert again is not None
        assert again["username"] == "bob"

    async def test_get_by_username(self, async_session):
        repo = UserRepository(async_session)
        await repo.ensure_default_user("alice")
        user = await repo.get_by_username("alice")
        assert user is not None
        assert user["username"] == "alice"
        assert await repo.get_by_username("nobody") is None


class TestEnsureDefaultUserStartup:
    async def test_syncs_env_username(self, monkeypatch):
        """启动同步：把 AUTH_USERNAME 写入 users 表。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        import lib.db

        monkeypatch.setattr(lib.db, "async_session_factory", factory)
        with patch.dict(os.environ, {"AUTH_USERNAME": "deploy-user", "AUTH_PASSWORD": "x"}):
            await auth_module.ensure_default_user()

        async with factory() as session:
            user = await UserRepository(session).get_by_id("default")
        assert user is not None
        assert user["username"] == "deploy-user"
        await engine.dispose()

    async def test_skipped_when_auth_disabled(self, monkeypatch):
        """AUTH_ENABLED=false 时不做任何写入。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        import lib.db

        monkeypatch.setattr(lib.db, "async_session_factory", factory)
        with patch.dict(os.environ, {"AUTH_ENABLED": "false", "AUTH_USERNAME": "ghost"}):
            await auth_module.ensure_default_user()

        async with factory() as session:
            user = await UserRepository(session).get_by_id("default")
        assert user is None
        await engine.dispose()


class TestRequireAdmin:
    async def test_admin_allowed(self):
        """admin 角色放行。"""
        user = auth_module.CurrentUserInfo(id="default", sub="admin", role="admin")
        result = await auth_module.require_admin(user, lambda key, **kw: key)
        assert result is user

    async def test_user_forbidden(self):
        """普通用户角色抛 403。"""
        from fastapi import HTTPException

        user = auth_module.CurrentUserInfo(id="u1", sub="alice", role="user")
        with pytest.raises(HTTPException) as exc_info:
            await auth_module.require_admin(user, lambda key, **kw: key)
        assert exc_info.value.status_code == 403


class TestRoleResolutionFailClosed:
    async def test_missing_record_resolves_user(self, monkeypatch):
        """users 表无记录时按普通用户处理，不静默提权为 admin。"""
        from lib.db.repositories.user_repository import UserRepository

        async def _none(self, username: str):
            return None

        monkeypatch.setattr(UserRepository, "get_by_username", _none)
        user = await auth_module._payload_to_user({"sub": "ghost"})
        assert user.role == "user"
        assert user.auth_via == "jwt"

    async def test_db_error_resolves_user(self, monkeypatch):
        """查库异常时按普通用户处理（fail-closed）。"""
        import lib.db

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(lib.db, "async_session_factory", _boom)
        user = await auth_module._payload_to_user({"sub": "admin"})
        assert user.role == "user"

    async def test_apikey_payload_keeps_sub_and_via(self, monkeypatch):
        """API Key 载荷保留 apikey: 前缀 sub，并以 auth_via 标记来源。"""
        from lib.db.repositories.user_repository import UserRepository

        async def _by_id(self, user_id: str):
            return {"id": "default", "username": "admin", "role": "admin", "is_active": True}

        monkeypatch.setattr(UserRepository, "get_by_id", _by_id)
        user = await auth_module._payload_to_user({"sub": "apikey:test-key", "via": "apikey", "user_id": "default"})
        assert user.sub == "apikey:test-key"
        assert user.auth_via == "apikey"
        assert user.role == "admin"


class TestAdminEndpoints:
    @pytest.fixture()
    def app(self):
        app = FastAPI()
        app.include_router(api_keys.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
        return app

    def test_api_keys_forbidden_for_user(self, app):
        """非 admin 调用 API Key 管理端点返回 403。"""
        from server.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: auth_module.CurrentUserInfo(
            id="u1", sub="alice", role="user"
        )
        with TestClient(app) as client:
            resp = client.get("/api/v1/api-keys")
            assert resp.status_code == 403

    def test_api_keys_allowed_for_admin(self, app):
        """admin 调用 API Key 列表端点正常返回。"""
        from server.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: auth_module.CurrentUserInfo(
            id="default", sub="admin", role="admin"
        )
        with TestClient(app) as client:
            resp = client.get("/api/v1/api-keys")
            assert resp.status_code == 200

    def test_api_key_cannot_manage_api_keys(self, app):
        """API Key 自身不能管理 API Key（jwt_auth_required，即使 role 为 admin）。"""
        from server.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: auth_module.CurrentUserInfo(
            id="default", sub="apikey:test-key", role="admin", auth_via="apikey"
        )
        with TestClient(app) as client:
            resp = client.get("/api/v1/api-keys")
            assert resp.status_code == 403
