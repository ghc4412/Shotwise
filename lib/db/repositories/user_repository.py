"""Async repository for user records.

users 表是多用户基础设施的落点：认证链路由 env 单账号驱动（见
``server/auth.py``），但当前登录用户的身份与角色（admin/user）从这张表
读取，权限判断以 DB 记录为准。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from lib.db.base import utc_now
from lib.db.models.user import User
from lib.db.repositories.base import BaseRepository


def _row_to_dict(row: User) -> dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "role": row.role,
        "is_active": row.is_active,
        "github_id": row.github_id,
    }


class UserRepository(BaseRepository):
    async def get_by_username(self, username: str) -> dict[str, Any] | None:
        """Look up a user by login username. Returns None when absent."""
        stmt = select(User).where(User.username == username)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _row_to_dict(row) if row is not None else None

    async def get_by_github_id(self, github_id: str) -> dict[str, Any] | None:
        """Look up a user by GitHub account id. Returns None when absent."""
        stmt = select(User).where(User.github_id == github_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _row_to_dict(row) if row is not None else None

    async def get_or_create_github_user(self, github_id: str, username: str) -> dict[str, Any]:
        """Resolve the user record for a GitHub account, creating it on first sign-in.

        GitHub login is used as the Shotwise username. If that name is already
        taken by another record (e.g. the env admin), a deterministic ``-gh``
        suffix is tried so repeated sign-ins resolve to the same user.
        """
        existing = await self.get_by_github_id(github_id)
        if existing is not None:
            return existing

        candidate = username
        taken = await self.get_by_username(candidate)
        if taken is not None and taken.get("github_id") != github_id:
            candidate = f"{username}-gh"
            if await self.get_by_username(candidate) is not None:
                raise ValueError(f"GitHub username unavailable: {username}")

        row = User(
            id=f"github-{github_id}",
            username=candidate,
            role="user",
            is_active=True,
            github_id=github_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return _row_to_dict(row)

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Look up a user by primary key. Returns None when absent."""
        stmt = select(User).where(User.id == user_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _row_to_dict(row) if row is not None else None

    async def ensure_default_user(self, username: str, *, role: str = "admin") -> dict[str, Any]:
        """Upsert the singleton deployment user (id="default") to match env config.

        Called at startup so the users table always carries a record for the
        current ``AUTH_USERNAME`` (default "admin"); existing rows are updated
        in place so a renamed env username takes effect without losing the
        stable "default" id that foreign keys reference.
        """
        from lib.db.base import DEFAULT_USER_ID

        existing = await self.get_by_id(DEFAULT_USER_ID)
        if existing is None:
            row = User(
                id=DEFAULT_USER_ID,
                username=username,
                role=role,
                is_active=True,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.session.add(row)
            await self.session.flush()
            return _row_to_dict(row)

        if existing["username"] != username or existing["role"] != role:
            await self.session.execute(
                update(User)
                .where(User.id == DEFAULT_USER_ID)
                .values(username=username, role=role, updated_at=utc_now())
            )
            await self.session.flush()
            existing.update({"username": username, "role": role})
        return existing


__all__ = ["UserRepository"]
