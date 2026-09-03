"""Agent 凭证 Repository。"""

from __future__ import annotations

from sqlalchemy import delete, select, update

from lib.db.base import DEFAULT_USER_ID
from lib.db.models.agent_credential import AgentAnthropicCredential
from lib.db.repositories.base import BaseRepository

# 支持的 Agent SDK 类型；缺省值保持向后兼容（存量凭证均为 claude）
SDK_TYPE_CLAUDE = "claude"
SDK_TYPE_OPENAI = "openai"
SDK_TYPES = (SDK_TYPE_CLAUDE, SDK_TYPE_OPENAI)


class AgentCredentialRepository(BaseRepository):
    """凭证 CRUD + (user, sdk_type) 维度 active 互斥切换。

    NOTE: 调用方需在合适的边界 commit。本类只 flush，不 commit。
    """

    async def create(
        self,
        *,
        preset_id: str,
        display_name: str,
        base_url: str,
        api_key: str,
        model: str | None = None,
        haiku_model: str | None = None,
        sonnet_model: str | None = None,
        opus_model: str | None = None,
        subagent_model: str | None = None,
        model_map: list | None = None,
        sdk_type: str = SDK_TYPE_CLAUDE,
        protocol: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentAnthropicCredential:
        cred = AgentAnthropicCredential(
            user_id=user_id,
            sdk_type=sdk_type,
            protocol=protocol or ("anthropic_messages" if sdk_type == SDK_TYPE_CLAUDE else "chat_completions"),
            preset_id=preset_id,
            display_name=display_name,
            base_url=base_url,
            api_key=api_key,
            model=model,
            haiku_model=haiku_model,
            sonnet_model=sonnet_model,
            opus_model=opus_model,
            subagent_model=subagent_model,
            model_map=model_map,
            is_active=False,
        )
        self.session.add(cred)
        await self.session.flush()
        return cred

    async def get(self, cred_id: int) -> AgentAnthropicCredential | None:
        stmt = select(AgentAnthropicCredential).where(AgentAnthropicCredential.id == cred_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self, sdk_type: str | None = None, user_id: str = DEFAULT_USER_ID
    ) -> list[AgentAnthropicCredential]:
        stmt = select(AgentAnthropicCredential).where(AgentAnthropicCredential.user_id == user_id)
        if sdk_type is not None:
            stmt = stmt.where(AgentAnthropicCredential.sdk_type == sdk_type)
        stmt = stmt.order_by(AgentAnthropicCredential.id)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def get_active(
        self, sdk_type: str = SDK_TYPE_CLAUDE, user_id: str = DEFAULT_USER_ID
    ) -> AgentAnthropicCredential | None:
        stmt = select(AgentAnthropicCredential).where(
            AgentAnthropicCredential.user_id == user_id,
            AgentAnthropicCredential.sdk_type == sdk_type,
            AgentAnthropicCredential.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, cred_id: int, **kwargs) -> AgentAnthropicCredential | None:
        cred = await self.get(cred_id)
        if cred is None:
            return None
        for k, v in kwargs.items():
            setattr(cred, k, v)
        await self.session.flush()
        return cred

    async def set_active(self, cred_id: int, user_id: str = DEFAULT_USER_ID) -> None:
        """互斥切 active：先把同 user 同 sdk_type 全置 False，再把目标置 True。

        Raises:
            ValueError: cred_id 不存在或不属于该 user
        """
        cred = await self.get(cred_id)
        if cred is None or cred.user_id != user_id:
            raise ValueError(f"credential id={cred_id} not found")
        # SQLite 的 partial unique index 在同事务内中间态可能违反，所以先全清再设
        await self.session.execute(
            update(AgentAnthropicCredential)
            .where(
                AgentAnthropicCredential.user_id == user_id,
                AgentAnthropicCredential.sdk_type == cred.sdk_type,
                AgentAnthropicCredential.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self.session.flush()
        cred.is_active = True
        await self.session.flush()

    async def delete(self, cred_id: int) -> bool:
        """删除非 active 凭证。

        Returns:
            True: 删除成功；False: 凭证不存在。

        Raises:
            ValueError: 试图删除当前 active 凭证。
        """
        cred = await self.get(cred_id)
        if cred is None:
            return False
        if cred.is_active:
            raise ValueError("cannot delete active credential; activate another first")
        await self.session.execute(delete(AgentAnthropicCredential).where(AgentAnthropicCredential.id == cred_id))
        await self.session.flush()
        return True
