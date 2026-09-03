"""Episode target-duration planning routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lib.api_errors import NotFoundError
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.episode_duration_plan import EpisodeDurationRevisionConflict
from lib.i18n import Translator
from lib.project_manager import EpisodeScriptReboundError, ProjectManager, get_project_manager
from server.auth import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_name}/episodes/{episode}/duration-plan",
    tags=["episode-duration"],
)


class DurationPlanInput(BaseModel):
    target_seconds: int = Field(ge=1)
    strategy: Literal["equal", "proportional", "manual"] = "equal"
    manual_allocations: dict[str, int] = Field(default_factory=dict)


class DurationPlanMutation(DurationPlanInput):
    expected_revision: str = Field(min_length=1)


class DurationLockInput(BaseModel):
    locked: bool
    expected_revision: str = Field(min_length=1)


async def _supported_durations(project_name: str, manager: ProjectManager) -> tuple[int, ...]:
    project = await asyncio.to_thread(manager.load_project, project_name)
    capabilities = await ConfigResolver(async_session_factory).video_capabilities_for_project(project)
    raw = capabilities.get("supported_durations")
    if not isinstance(raw, list):
        raise ValueError("supported durations are unavailable")
    durations = tuple(
        sorted({value for value in raw if isinstance(value, int) and not isinstance(value, bool) and value > 0})
    )
    if not durations:
        raise ValueError("supported durations are unavailable")
    return durations


def _raise_duration_error(exc: Exception, project_name: str, _t: Translator) -> None:
    if isinstance(exc, EpisodeDurationRevisionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "episode_duration_revision_conflict",
                "message": _t("episode_duration_revision_conflict"),
                "actual_revision": exc.actual,
            },
        ) from exc
    if isinstance(exc, EpisodeScriptReboundError):
        logger.info("episode script rebound during duration update: %s", exc)
        raise HTTPException(status_code=409, detail=_t("episode_duration_script_rebound")) from exc
    if isinstance(exc, FileNotFoundError):
        raise NotFoundError("project_not_found", name=project_name) from exc
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=_t("episode_duration_resource_not_found")) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=422,
            detail=_t("episode_duration_invalid", details=str(exc)),
        ) from exc
    raise exc


@router.get("")
async def get_duration_plan(project_name: str, episode: int, _user: CurrentUser, _t: Translator):
    try:
        return await asyncio.to_thread(get_project_manager().load_episode_duration_state, project_name, episode)
    except Exception as exc:
        _raise_duration_error(exc, project_name, _t)


@router.put("")
async def save_duration_plan(
    project_name: str, episode: int, body: DurationPlanMutation, _user: CurrentUser, _t: Translator
):
    try:
        return await asyncio.to_thread(
            get_project_manager().save_episode_duration_plan,
            project_name,
            episode,
            expected_revision=body.expected_revision,
            target_seconds=body.target_seconds,
            strategy=body.strategy,
            manual_allocations=body.manual_allocations,
        )
    except Exception as exc:
        _raise_duration_error(exc, project_name, _t)


@router.post("/preview")
async def preview_duration_plan(
    project_name: str, episode: int, body: DurationPlanInput, _user: CurrentUser, _t: Translator
):
    manager = get_project_manager()
    try:
        durations = await _supported_durations(project_name, manager)
        return await asyncio.to_thread(
            manager.preview_episode_duration_plan,
            project_name,
            episode,
            target_seconds=body.target_seconds,
            strategy=body.strategy,
            manual_allocations=body.manual_allocations,
            supported_durations=durations,
        )
    except Exception as exc:
        _raise_duration_error(exc, project_name, _t)


@router.post("/apply")
async def apply_duration_plan(
    project_name: str, episode: int, body: DurationPlanMutation, _user: CurrentUser, _t: Translator
):
    manager = get_project_manager()
    try:
        durations = await _supported_durations(project_name, manager)
        return await asyncio.to_thread(
            manager.apply_episode_duration_plan,
            project_name,
            episode,
            expected_revision=body.expected_revision,
            target_seconds=body.target_seconds,
            strategy=body.strategy,
            manual_allocations=body.manual_allocations,
            supported_durations=durations,
        )
    except Exception as exc:
        _raise_duration_error(exc, project_name, _t)


@router.patch("/items/{resource_id}/lock")
async def set_duration_lock(
    project_name: str,
    episode: int,
    resource_id: str,
    body: DurationLockInput,
    _user: CurrentUser,
    _t: Translator,
):
    try:
        return await asyncio.to_thread(
            get_project_manager().set_episode_duration_lock,
            project_name,
            episode,
            resource_id,
            locked=body.locked,
            expected_revision=body.expected_revision,
        )
    except Exception as exc:
        _raise_duration_error(exc, project_name, _t)
