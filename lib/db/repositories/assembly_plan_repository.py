"""Repository for user-scoped media assembly plans and immutable revisions."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.assembly_plan import AssemblyPlan, AssemblyPlanRevision
from lib.db.repositories.base import BaseRepository


class AssemblyPlanRepository(BaseRepository):
    """Persist assembly plan envelopes and their immutable revision snapshots."""

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_owned(self, plan_id: str, *, user_id: str) -> AssemblyPlan | None:
        """Return a plan only when it belongs to the requesting user."""
        return await self.session.scalar(
            select(AssemblyPlan).where(AssemblyPlan.id == plan_id, AssemblyPlan.user_id == user_id)
        )

    async def get_current_revision(self, plan: AssemblyPlan) -> AssemblyPlanRevision | None:
        """Load the revision selected by the plan's current revision pointer."""
        return await self.session.scalar(
            select(AssemblyPlanRevision).where(
                AssemblyPlanRevision.plan_id == plan.id,
                AssemblyPlanRevision.version_number == plan.current_revision_number,
            )
        )

    async def list_by_project(self, *, user_id: str, project_name: str) -> list[AssemblyPlan]:
        """List plans in stable most-recently-updated order."""
        result = await self.session.execute(
            select(AssemblyPlan)
            .where(AssemblyPlan.user_id == user_id, AssemblyPlan.project_name == project_name)
            .order_by(AssemblyPlan.updated_at.desc(), AssemblyPlan.id.desc())
        )
        return list(result.scalars().all())

    async def add_plan(self, plan: AssemblyPlan, revision: AssemblyPlanRevision) -> None:
        """Add a new plan together with its first revision."""
        self.session.add_all([plan, revision])
        await self.session.flush()

    async def add_revision(self, revision: AssemblyPlanRevision) -> None:
        """Persist one immutable revision."""
        self.session.add(revision)
        await self.session.flush()

    async def flush(self) -> None:
        """Flush mutable plan state without committing the caller's transaction."""
        await self.session.flush()

    async def advance_revision(
        self,
        plan: AssemblyPlan,
        *,
        expected_revision: int,
        new_fingerprint: str,
        updated_at,
    ) -> bool:
        """Advance the current revision with an optimistic compare-and-swap."""
        result = await self.session.execute(
            update(AssemblyPlan)
            .where(AssemblyPlan.id == plan.id, AssemblyPlan.current_revision_number == expected_revision)
            .values(
                current_revision_number=expected_revision + 1,
                current_source_fingerprint=new_fingerprint,
                status="draft",
                preview_revision_number=None,
                preview_ready_at=None,
                render_confirmed_by=None,
                render_confirmed_at=None,
                updated_at=updated_at,
            )
        )
        if int(getattr(result, "rowcount", 0)) != 1:
            return False
        await self.session.refresh(plan)
        return True


__all__ = ["AssemblyPlanRepository"]
