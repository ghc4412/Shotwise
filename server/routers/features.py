"""Public rollout state for feature-aware frontend navigation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from lib.feature_flags import (
    creation_metric_snapshot,
    feature_audit_snapshot,
    feature_snapshot,
    validate_rollout_configuration,
)
from server.services import creation_plans as creation_plan_service

router = APIRouter()


@router.get("/feature-flags")
async def get_feature_flags() -> dict[str, object]:
    return {"features": feature_snapshot()}


@router.get("/feature-flags/metrics")
async def get_feature_metrics(session: AsyncSession = Depends(get_async_session)) -> dict[str, object]:
    """Expose rollout diagnostics and coarse compatibility aggregates only."""

    return {
        "features": feature_snapshot(),
        "configuration": feature_audit_snapshot(),
        "creation": creation_metric_snapshot(),
        "compatibility": await creation_plan_service.compatibility_metrics(session),
    }


@router.get("/feature-flags/validate")
async def validate_feature_flags() -> dict[str, object]:
    """Return actionable, non-secret rollout configuration diagnostics."""

    return validate_rollout_configuration()
