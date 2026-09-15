"""Persistence and execution service for deterministic media renders."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.app_data_dir import app_data_dir
from lib.db import async_session_factory
from lib.db.base import utc_now
from lib.db.models.assembly_plan import AssemblyPlan, AssemblyPlanRevision
from lib.db.models.render_job import RenderArtifact, RenderJob, RenderReviewSnapshot
from lib.db.repositories.assembly_plan_repository import AssemblyPlanRepository
from lib.media_assembly.audio import AudioMixConfig, AudioTrack, VolumePoint
from lib.media_assembly.rendering import (
    RenderToolError,
    burn_in_subtitles,
    file_fingerprint,
    probe_media,
    render_low_resolution_preview,
    render_video,
    resolve_tool,
)
from lib.media_assembly.review import (
    audio_level_check,
    audio_quality_check,
    classify_black_frame_edges,
    expected_timeline_duration,
    parse_audio_metrics_log,
    parse_silencedetect_log,
    subtitle_bounds_check,
)
from lib.media_assembly.subtitles import SubtitleValidationError, generate_srt, generate_vtt
from lib.path_safety import PathTraversalError, safe_join
from lib.project_manager import ProjectManager
from server.services import media_assembly, media_audio


class RenderJobNotFoundError(LookupError):
    """Raised when a render job or artifact is absent or not owned by the caller."""


class RenderArtifactNotFoundError(LookupError):
    """Raised when an artifact is absent or not owned by the caller."""


class FinalRenderNotReadyError(LookupError):
    """Raised when the current revision has no final render artifact."""


class FinalRenderReviewError(RuntimeError):
    """Raised when deterministic inspection of a final render cannot complete."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RenderReviewConflictError(RuntimeError):
    """Raised when a final review cannot be confirmed for the current artifact."""

    def __init__(self, code: str, *, status: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class SubtitleExportError(ValueError):
    """Raised when a revision contains invalid subtitle data."""


class RenderRevisionConflictError(RuntimeError):
    """Raised when a render no longer targets the plan's current revision."""

    def __init__(self, code: str = "revision_conflict", *, status: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class RenderJobConflictError(RuntimeError):
    """Raised when the job lifecycle or preview gate rejects an operation."""

    def __init__(self, code: str, *, status: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _job_payload(job: RenderJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "plan_id": job.plan_id,
        "project_name": job.project_name,
        "user_id": job.user_id,
        "revision_number": job.revision_number,
        "kind": job.kind,
        "status": job.status,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "input_fingerprint": job.input_fingerprint,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat(),
    }


def _artifact_payload(artifact: RenderArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "render_job_id": artifact.render_job_id,
        "plan_id": artifact.plan_id,
        "project_name": artifact.project_name,
        "user_id": artifact.user_id,
        "revision_number": artifact.revision_number,
        "kind": artifact.kind,
        "relative_path": artifact.relative_path,
        "mime_type": artifact.mime_type,
        "size_bytes": artifact.size_bytes,
        "duration_seconds": artifact.duration_seconds,
        "width": artifact.width,
        "height": artifact.height,
        "fingerprint": artifact.fingerprint,
        "created_at": artifact.created_at.isoformat(),
    }


def _review_snapshot_payload(snapshot: RenderReviewSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "artifact_id": snapshot.artifact_id,
        "plan_id": snapshot.plan_id,
        "project_name": snapshot.project_name,
        "user_id": snapshot.user_id,
        "revision_number": snapshot.revision_number,
        "source_fingerprint": snapshot.source_fingerprint,
        "artifact_fingerprint": snapshot.artifact_fingerprint,
        "status": snapshot.status,
        "checks": json.loads(snapshot.checks_json),
        "created_at": snapshot.created_at.isoformat(),
        "confirmed_by": snapshot.confirmed_by,
        "confirmed_at": snapshot.confirmed_at.isoformat() if snapshot.confirmed_at else None,
    }


async def _owned_plan(session: AsyncSession, plan_id: str, user_id: str) -> AssemblyPlan:
    plan = await AssemblyPlanRepository(session).get_owned(plan_id, user_id=user_id)
    if plan is None:
        raise media_assembly.AssemblyPlanNotFoundError(plan_id)
    return plan


async def _current_revision(session: AsyncSession, plan: AssemblyPlan) -> AssemblyPlanRevision:
    revision = await AssemblyPlanRepository(session).get_current_revision(plan)
    if revision is None:
        raise RenderRevisionConflictError("current_revision_missing", status=plan.status)
    return revision


async def _owned_job(session: AsyncSession, job_id: str, user_id: str) -> RenderJob:
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id, RenderJob.user_id == user_id))
    if job is None:
        raise RenderJobNotFoundError(job_id)
    return job


async def _owned_artifact(session: AsyncSession, artifact_id: str, user_id: str) -> RenderArtifact:
    artifact = await session.scalar(
        select(RenderArtifact).where(RenderArtifact.id == artifact_id, RenderArtifact.user_id == user_id)
    )
    if artifact is None:
        raise RenderArtifactNotFoundError(artifact_id)
    return artifact


def _project_root(project_name: str) -> Path:
    return ProjectManager(app_data_dir()).get_project_path(project_name)


def _artifact_path(project_root: Path, job_id: str, revision_number: int) -> tuple[str, Path]:
    relative = Path("render_artifacts") / "preview" / f"revision-{revision_number}" / f"preview-{job_id}.mp4"
    try:
        return relative.as_posix(), safe_join(project_root, relative)
    except (PathTraversalError, TypeError, ValueError) as exc:
        raise RenderJobConflictError("artifact_path_invalid") from exc


def _final_artifact_path(project_root: Path, job_id: str, revision_number: int) -> tuple[str, Path]:
    relative = Path("render_artifacts") / "final" / f"revision-{revision_number}" / f"final-{job_id}.mp4"
    try:
        return relative.as_posix(), safe_join(project_root, relative)
    except (PathTraversalError, TypeError, ValueError) as exc:
        raise RenderJobConflictError("artifact_path_invalid") from exc


def _safe_error(exc: Exception, *, kind: str = "preview") -> tuple[str, str]:
    if isinstance(exc, RenderToolError):
        code = exc.code
        message = exc.message
    elif isinstance(exc, RenderRevisionConflictError):
        code = exc.code
        message = str(exc)
    elif isinstance(exc, RenderJobConflictError):
        code = exc.code
        message = str(exc)
    else:
        code = "render_failed"
        message = f"{kind} render failed"
    return code[:64], message[:2000]


async def create_preview_job(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    revision_number: int | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Create a queued preview job for the plan's current immutable revision."""
    if max_attempts < 1 or max_attempts > 10:
        raise RenderJobConflictError("invalid_max_attempts")
    plan = await _owned_plan(session, plan_id, user_id)
    revision = await _current_revision(session, plan)
    target_revision = revision_number if revision_number is not None else plan.current_revision_number
    if target_revision != plan.current_revision_number or revision.version_number != target_revision:
        raise RenderRevisionConflictError(status=plan.status)
    if plan.status != "confirmed":
        raise RenderJobConflictError("preview_requires_confirmed_plan", status=plan.status)
    active = await session.scalar(
        select(RenderJob).where(
            RenderJob.plan_id == plan.id,
            RenderJob.user_id == user_id,
            RenderJob.revision_number == target_revision,
            RenderJob.kind == "preview",
            RenderJob.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        raise RenderJobConflictError("preview_job_already_running", status=active.status)

    now = utc_now()
    job = RenderJob(
        id=str(uuid.uuid4()),
        plan_id=plan.id,
        project_name=plan.project_name,
        user_id=user_id,
        revision_number=target_revision,
        kind="preview",
        status="queued",
        attempt=0,
        max_attempts=max_attempts,
        input_fingerprint=revision.source_fingerprint,
        error_code=None,
        error_message=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        updated_at=now,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise RenderJobConflictError("preview_job_already_running") from exc
    try:
        await media_assembly.transition_plan(
            session,
            plan.id,
            user_id=user_id,
            target_status="preview_pending",
        )
    except media_assembly.AssemblyPlanConflictError as exc:
        raise RenderJobConflictError(exc.code, status=exc.status) from exc
    return _job_payload(job)


async def create_final_job(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    revision_number: int | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Queue a final render only for the revision the user explicitly confirmed."""
    if max_attempts < 1 or max_attempts > 10:
        raise RenderJobConflictError("invalid_max_attempts")
    plan = await _owned_plan(session, plan_id, user_id)
    revision = await _current_revision(session, plan)
    target_revision = revision_number if revision_number is not None else plan.current_revision_number
    _validate_final_gate(plan, revision, target_revision)

    active = await session.scalar(
        select(RenderJob).where(
            RenderJob.plan_id == plan.id,
            RenderJob.user_id == user_id,
            RenderJob.revision_number == target_revision,
            RenderJob.kind == "final",
            RenderJob.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        raise RenderJobConflictError("final_job_already_running", status=active.status)

    now = utc_now()
    job = RenderJob(
        id=str(uuid.uuid4()),
        plan_id=plan.id,
        project_name=plan.project_name,
        user_id=user_id,
        revision_number=target_revision,
        kind="final",
        status="queued",
        attempt=0,
        max_attempts=max_attempts,
        input_fingerprint=revision.source_fingerprint,
        error_code=None,
        error_message=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        updated_at=now,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise RenderJobConflictError("final_job_already_running") from exc
    return _job_payload(job)


def _validate_final_gate(plan: AssemblyPlan, revision: AssemblyPlanRevision, target_revision: int) -> None:
    if target_revision != plan.current_revision_number or revision.version_number != target_revision:
        raise RenderRevisionConflictError(status=plan.status)
    if revision.source_fingerprint != plan.current_source_fingerprint:
        raise RenderRevisionConflictError("source_fingerprint_conflict", status=plan.status)
    if plan.preview_revision_number != target_revision:
        raise RenderJobConflictError("preview_revision_required", status=plan.status)
    if plan.preview_confirmed_by is None or plan.preview_confirmed_at is None:
        raise RenderJobConflictError("preview_confirmation_required", status=plan.status)
    if plan.render_confirmed_by is None or plan.render_confirmed_at is None:
        raise RenderJobConflictError("render_confirmation_required", status=plan.status)
    if plan.status != "render_pending":
        raise RenderJobConflictError("final_render_pending_required", status=plan.status)


def _validate_final_revision(
    plan: AssemblyPlan,
    revision: AssemblyPlanRevision,
    job: RenderJob,
    *,
    allow_statuses: set[str],
) -> None:
    """Validate immutable inputs again after a worker has claimed a job."""
    if plan.current_revision_number != job.revision_number or revision.version_number != job.revision_number:
        raise RenderRevisionConflictError(status=plan.status)
    if revision.source_fingerprint != job.input_fingerprint:
        raise RenderRevisionConflictError("source_fingerprint_conflict", status=plan.status)
    if revision.source_fingerprint != plan.current_source_fingerprint:
        raise RenderRevisionConflictError("source_fingerprint_conflict", status=plan.status)
    if plan.preview_revision_number != job.revision_number:
        raise RenderJobConflictError("preview_revision_required", status=plan.status)
    if plan.preview_confirmed_by is None or plan.preview_confirmed_at is None:
        raise RenderJobConflictError("preview_confirmation_required", status=plan.status)
    if plan.render_confirmed_by is None or plan.render_confirmed_at is None:
        raise RenderJobConflictError("render_confirmation_required", status=plan.status)
    if plan.status not in allow_statuses:
        raise RenderJobConflictError("final_render_status_conflict", status=plan.status)


async def get_render_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    payload = _job_payload(job)
    artifact = await session.scalar(
        select(RenderArtifact)
        .where(RenderArtifact.render_job_id == job.id, RenderArtifact.user_id == user_id)
        .order_by(RenderArtifact.created_at.desc())
    )
    payload["artifact"] = _artifact_payload(artifact) if artifact else None
    return payload


async def list_render_jobs(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    await _owned_plan(session, plan_id, user_id)
    statement = select(RenderJob).where(RenderJob.plan_id == plan_id, RenderJob.user_id == user_id)
    if kind is not None:
        statement = statement.where(RenderJob.kind == kind)
    result = await session.execute(statement.order_by(RenderJob.created_at.desc(), RenderJob.id.desc()))
    return [_job_payload(job) for job in result.scalars().all()]


async def retry_preview_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    if job.status != "failed":
        raise RenderJobConflictError("retry_requires_failed_job", status=job.status)
    if job.attempt >= job.max_attempts:
        raise RenderJobConflictError("retry_limit_reached", status=job.status)
    plan = await _owned_plan(session, job.plan_id, user_id)
    if plan.current_revision_number != job.revision_number:
        raise RenderRevisionConflictError(status=plan.status)
    if plan.status not in {"preview_pending", "failed"}:
        raise RenderJobConflictError("preview_retry_not_allowed", status=plan.status)
    if plan.status == "failed":
        try:
            await media_assembly.transition_plan(
                session,
                plan.id,
                user_id=user_id,
                target_status="confirmed",
            )
            await media_assembly.transition_plan(
                session,
                plan.id,
                user_id=user_id,
                target_status="preview_pending",
            )
        except media_assembly.AssemblyPlanConflictError as exc:
            raise RenderJobConflictError(exc.code, status=exc.status) from exc
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.updated_at = utc_now()
    await session.flush()
    return _job_payload(job)


async def retry_final_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    """Requeue a failed final job without changing its confirmed revision."""
    job = await _owned_job(session, job_id, user_id)
    if job.kind != "final":
        raise RenderJobConflictError("final_retry_requires_final_job", status=job.status)
    if job.status != "failed":
        raise RenderJobConflictError("retry_requires_failed_job", status=job.status)
    if job.attempt >= job.max_attempts:
        raise RenderJobConflictError("retry_limit_reached", status=job.status)
    plan = await _owned_plan(session, job.plan_id, user_id)
    revision = await _current_revision(session, plan)
    _validate_final_revision(plan, revision, job, allow_statuses={"failed"})

    result = await session.execute(
        update(AssemblyPlan)
        .where(
            AssemblyPlan.id == plan.id,
            AssemblyPlan.user_id == user_id,
            AssemblyPlan.status == "failed",
            AssemblyPlan.current_revision_number == job.revision_number,
            AssemblyPlan.current_source_fingerprint == job.input_fingerprint,
            AssemblyPlan.preview_revision_number == job.revision_number,
            AssemblyPlan.preview_confirmed_by.is_not(None),
            AssemblyPlan.preview_confirmed_at.is_not(None),
            AssemblyPlan.render_confirmed_by.is_not(None),
            AssemblyPlan.render_confirmed_at.is_not(None),
        )
        .values(status="render_pending", updated_at=utc_now())
    )
    if int(getattr(result, "rowcount", 0)) != 1:
        raise RenderJobConflictError("final_retry_confirmation_conflict", status=plan.status)

    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.updated_at = utc_now()
    plan.status = "render_pending"
    plan.updated_at = job.updated_at
    await session.flush()
    return _job_payload(job)


class RenderConfigError(RenderToolError):
    """Raised when immutable audio or subtitle configuration is not executable."""

    def __init__(self, message: str) -> None:
        super().__init__("render_config_invalid", message)


def _as_object(value: object, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RenderConfigError(f"{name} must be an object")
    return dict(value)


def _number(value: object, *, name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderConfigError(f"{name} must be a number")
    return float(value)


def _volume_points(value: object, *, name: str) -> tuple[VolumePoint, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RenderConfigError(f"{name} must be a list")
    points: list[VolumePoint] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise RenderConfigError(f"{name}[{index}] must be an object")
        points.append(
            VolumePoint(
                time_seconds=_number(raw.get("time_seconds"), name=f"{name}[{index}].time_seconds", default=0),
                volume=_number(raw.get("volume"), name=f"{name}[{index}].volume", default=1),
            )
        )
    return tuple(points)


def _audio_pipeline_config(
    audio: object,
    *,
    duration_seconds: float,
    timeline: Sequence[object],
) -> tuple[AudioMixConfig, tuple[AudioTrack, ...], bool]:
    config = _as_object(audio, name="audio")
    raw_tracks = config.get("tracks", [])
    if not isinstance(raw_tracks, Sequence) or isinstance(raw_tracks, (str, bytes, bytearray)):
        raise RenderConfigError("audio.tracks must be a list")
    tracks: list[AudioTrack] = []
    kind_aliases = {
        "voiceover": "narration",
        "voice_over": "narration",
        "dialogue": "dialogue",
        "bgm": "bgm",
        "user_audio": "user_audio",
        "narration": "narration",
    }
    for index, raw in enumerate(raw_tracks):
        if not isinstance(raw, Mapping):
            raise RenderConfigError(f"audio.tracks[{index}] must be an object")
        source_ref = raw.get("source_ref")
        kind = raw.get("kind")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise RenderConfigError(f"audio.tracks[{index}].source_ref must be a non-empty string")
        if not isinstance(kind, str) or kind not in kind_aliases:
            raise RenderConfigError(f"audio.tracks[{index}].kind is unsupported")
        duration = raw.get("duration_seconds")
        tracks.append(
            AudioTrack(
                path=Path(source_ref),
                kind=kind_aliases[kind],  # type: ignore[arg-type]
                start_seconds=_number(raw.get("start_seconds"), name=f"audio.tracks[{index}].start_seconds", default=0),
                duration_seconds=(
                    _number(duration, name=f"audio.tracks[{index}].duration_seconds", default=0)
                    if duration is not None
                    else None
                ),
                volume=_number(raw.get("volume"), name=f"audio.tracks[{index}].volume", default=1),
                fade_in_seconds=_number(
                    raw.get("fade_in_seconds"), name=f"audio.tracks[{index}].fade_in_seconds", default=0
                ),
                fade_out_seconds=_number(
                    raw.get("fade_out_seconds"), name=f"audio.tracks[{index}].fade_out_seconds", default=0
                ),
                volume_envelope=_volume_points(
                    raw.get("volume_envelope"), name=f"audio.tracks[{index}].volume_envelope"
                ),
            )
        )
    timeline_policies = {
        item.get("audio_policy")
        for item in timeline
        if isinstance(item, Mapping) and isinstance(item.get("audio_policy"), str)
    }
    policy = config.get("original_policy", config.get("policy"))
    if policy is None:
        policy = "duck" if tracks else ("mute" if "mute" in timeline_policies else "keep")
    if not isinstance(policy, str):
        raise RenderConfigError("audio.original_policy must be a string")
    config_obj = AudioMixConfig(
        original_policy=policy,  # type: ignore[arg-type]
        duck_volume=_number(config.get("duck_volume"), name="audio.duck_volume", default=0.35),
        original_volume=_number(config.get("original_volume"), name="audio.original_volume", default=1),
        duration_seconds=duration_seconds,
        fade_in_seconds=_number(config.get("fade_in_seconds"), name="audio.fade_in_seconds", default=0),
        fade_out_seconds=_number(config.get("fade_out_seconds"), name="audio.fade_out_seconds", default=0),
        volume_envelope=_volume_points(config.get("volume_envelope"), name="audio.volume_envelope"),
    )
    explicit = any(
        key in config
        for key in (
            "original_policy",
            "policy",
            "duck_volume",
            "original_volume",
            "fade_in_seconds",
            "fade_out_seconds",
            "volume_envelope",
        )
    )
    return config_obj, tuple(tracks), bool(tracks) or (explicit and policy != "keep") or policy == "mute"


def _subtitle_payload(subtitle: object) -> tuple[str | None, str | None]:
    config = _as_object(subtitle, name="subtitle")
    raw_cues = config.get("cues", [])
    if not raw_cues:
        return None, None
    if not isinstance(raw_cues, Sequence) or isinstance(raw_cues, (str, bytes, bytearray)):
        raise RenderConfigError("subtitle.cues must be a list")
    cues: list[dict[str, object]] = []
    for index, raw in enumerate(raw_cues):
        if not isinstance(raw, Mapping):
            raise RenderConfigError(f"subtitle.cues[{index}] must be an object")
        cues.append(
            {
                "start_seconds": raw.get("start_seconds"),
                "end_seconds": raw.get("end_seconds"),
                "text": raw.get("text"),
                "identifier": raw.get("identifier", raw.get("id")),
            }
        )
    mode = config.get("mode", "burn_in")
    if not isinstance(mode, str) or mode not in {"burn_in", "burn_in_srt", "burn_in_vtt", "srt", "vtt", "sidecar"}:
        raise RenderConfigError("subtitle.mode is unsupported")
    if mode in {"vtt", "burn_in_vtt"}:
        return mode, generate_vtt(cues)
    return mode, generate_srt(cues)


async def render_preview_pipeline(
    timeline: list[dict[str, Any]],
    *,
    audio: object,
    subtitle: object,
    project_root: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float | None = None,
    base_renderer: object | None = None,
    probe_error_code: str = "preview_probe_invalid",
    packaging: object | None = None,
) -> dict[str, Any]:
    """Render a revision through hard-cut, audio, subtitle, and probe stages."""
    work_dir = output_path.parent / f".{output_path.stem}-pipeline-work"
    base_path = work_dir / "base.mp4"
    mixed_path = work_dir / "mixed.mp4"
    subtitled_path = work_dir / "subtitled.mp4"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        if base_renderer is None:
            base_result = await render_low_resolution_preview(
                timeline,
                project_root=project_root,
                output_path=base_path,
                width=width,
                height=height,
                fps=fps,
                packaging=packaging,
            )
        else:
            base_result = await render_video(
                timeline,
                project_root=project_root,
                output_path=base_path,
                width=width,
                height=height,
                fps=fps,
                preset="medium",
                crf=18,
                audio_bitrate="192k",
                packaging=packaging,
            )
        audio_config, tracks, should_mix = _audio_pipeline_config(
            audio, duration_seconds=float(base_result["duration_seconds"]), timeline=timeline
        )
        current_path = base_path
        if should_mix:
            base_probe = await probe_media(base_path, error_code=probe_error_code)
            await media_audio.mix_audio(
                project_root=project_root,
                video_path=current_path,
                output_path=mixed_path,
                tracks=tracks,
                config=audio_config,
                original_audio_present=bool(base_probe["audio_present"]),
            )
            current_path = mixed_path

        subtitle_mode, subtitle_text = _subtitle_payload(subtitle)
        if subtitle_mode is not None and subtitle_text is not None:
            subtitle_path = work_dir / ("captions.vtt" if subtitle_mode in {"vtt", "burn_in_vtt"} else "captions.srt")
            subtitle_path.write_text(subtitle_text, encoding="utf-8")
            if subtitle_mode in {"burn_in", "burn_in_srt", "burn_in_vtt"}:
                await burn_in_subtitles(
                    project_root=project_root,
                    video_path=current_path,
                    subtitle_path=subtitle_path,
                    output_path=subtitled_path,
                )
                current_path = subtitled_path

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        if current_path == base_path:
            current_path.replace(output_path)
            return base_result
        final_result = await probe_media(current_path, error_code=probe_error_code)
        current_path.replace(output_path)
        return final_result
    finally:
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)


async def render_final_pipeline(
    timeline: list[dict[str, Any]],
    *,
    audio: object,
    subtitle: object,
    project_root: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float | None = None,
    packaging: object | None = None,
) -> dict[str, Any]:
    """Render a final revision at its requested output dimensions and quality."""
    return await render_preview_pipeline(
        timeline,
        audio=audio,
        subtitle=subtitle,
        project_root=project_root,
        output_path=output_path,
        width=width,
        height=height,
        fps=fps,
        base_renderer=render_video,
        probe_error_code="final_probe_invalid",
        packaging=packaging,
    )


async def run_final_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    """Execute one confirmed final job with an atomic worker claim."""
    job = await _owned_job(session, job_id, user_id)
    if job.kind != "final":
        raise RenderJobConflictError("final_job_required", status=job.status)
    if job.status != "queued":
        raise RenderJobConflictError("job_not_queued", status=job.status)
    plan = await _owned_plan(session, job.plan_id, user_id)
    revision = await _current_revision(session, plan)
    _validate_final_revision(plan, revision, job, allow_statuses={"render_pending"})

    started_at = utc_now()
    claim_job = await session.execute(
        update(RenderJob)
        .where(
            RenderJob.id == job.id,
            RenderJob.user_id == user_id,
            RenderJob.kind == "final",
            RenderJob.status == "queued",
            RenderJob.revision_number == job.revision_number,
            RenderJob.input_fingerprint == job.input_fingerprint,
        )
        .values(status="running", attempt=RenderJob.attempt + 1, started_at=started_at, updated_at=started_at)
    )
    if int(getattr(claim_job, "rowcount", 0)) != 1:
        await session.rollback()
        raise RenderJobConflictError("job_claim_conflict", status="running")

    claim_plan = await session.execute(
        update(AssemblyPlan)
        .where(
            AssemblyPlan.id == plan.id,
            AssemblyPlan.user_id == user_id,
            AssemblyPlan.status == "render_pending",
            AssemblyPlan.current_revision_number == job.revision_number,
            AssemblyPlan.current_source_fingerprint == job.input_fingerprint,
            AssemblyPlan.preview_revision_number == job.revision_number,
            AssemblyPlan.preview_confirmed_by.is_not(None),
            AssemblyPlan.preview_confirmed_at.is_not(None),
            AssemblyPlan.render_confirmed_by.is_not(None),
            AssemblyPlan.render_confirmed_at.is_not(None),
        )
        .values(status="rendering", updated_at=started_at)
    )
    if int(getattr(claim_plan, "rowcount", 0)) != 1:
        await session.rollback()
        raise RenderJobConflictError("final_render_claim_conflict", status=plan.status)
    await session.commit()

    job = await _owned_job(session, job.id, user_id)
    plan = await _owned_plan(session, plan.id, user_id)
    revision = await _current_revision(session, plan)
    _validate_final_revision(plan, revision, job, allow_statuses={"rendering"})

    output_path: Path | None = None
    try:
        timeline = json.loads(revision.timeline_json)
        if not isinstance(timeline, list):
            raise RenderJobConflictError("timeline_invalid", status=plan.status)
        profile = json.loads(revision.output_profile_json)
        if not isinstance(profile, dict):
            raise RenderJobConflictError("output_profile_invalid", status=plan.status)
        width = profile.get("width", 1920)
        height = profile.get("height", 1080)
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
        ):
            raise RenderJobConflictError("output_profile_invalid", status=plan.status)
        fps_value = profile.get("fps")
        fps = float(fps_value) if isinstance(fps_value, (int, float)) and not isinstance(fps_value, bool) else None
        project_root = _project_root(plan.project_name)
        relative_path, output_path = _final_artifact_path(project_root, job.id, job.revision_number)
        await render_final_pipeline(
            timeline,
            audio=json.loads(revision.audio_json),
            subtitle=json.loads(revision.subtitle_json),
            packaging=json.loads(revision.packaging_json),
            project_root=project_root,
            output_path=output_path,
            width=width,
            height=height,
            fps=fps,
        )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise RenderToolError("final_output_missing", "final output is missing")
        probed = await probe_media(output_path, error_code="final_probe_invalid")
        if probed["duration_seconds"] <= 0 or probed["width"] <= 0 or probed["height"] <= 0:
            raise RenderToolError("final_probe_invalid", "ffprobe returned an unusable final video")
        artifact = RenderArtifact(
            id=str(uuid.uuid4()),
            render_job_id=job.id,
            plan_id=plan.id,
            project_name=plan.project_name,
            user_id=user_id,
            revision_number=job.revision_number,
            kind="final",
            relative_path=relative_path,
            mime_type="video/mp4",
            size_bytes=output_path.stat().st_size,
            duration_seconds=float(probed["duration_seconds"]),
            width=int(probed["width"]),
            height=int(probed["height"]),
            fingerprint=file_fingerprint(output_path),
            created_at=utc_now(),
        )
        session.add(artifact)
        completed_at = utc_now()
        job.status = "succeeded"
        job.error_code = None
        job.error_message = None
        job.completed_at = completed_at
        job.updated_at = completed_at
        completed_plan = await session.execute(
            update(AssemblyPlan)
            .where(
                AssemblyPlan.id == plan.id,
                AssemblyPlan.user_id == user_id,
                AssemblyPlan.status == "rendering",
                AssemblyPlan.current_revision_number == job.revision_number,
                AssemblyPlan.current_source_fingerprint == job.input_fingerprint,
            )
            .values(status="completed", updated_at=completed_at)
        )
        if int(getattr(completed_plan, "rowcount", 0)) != 1:
            raise RenderJobConflictError("final_completion_conflict", status=plan.status)
        await session.commit()
        return await get_render_job(session, job.id, user_id=user_id)
    except Exception as exc:
        if output_path is not None:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        # Rollback expires ORM instances. Capture immutable identifiers before it
        # so failure persistence never performs implicit async attribute loading.
        job_id_value = job.id
        plan_id_value = job.plan_id
        revision_number_value = job.revision_number
        input_fingerprint_value = job.input_fingerprint
        code, message = _safe_error(exc, kind="final")
        await session.rollback()
        failed = await _owned_job(session, job_id_value, user_id)
        failed.status = "failed"
        failed.error_code = code
        failed.error_message = message
        completed_at = utc_now()
        failed.completed_at = completed_at
        failed.updated_at = completed_at
        await session.execute(
            update(AssemblyPlan)
            .where(
                AssemblyPlan.id == plan_id_value,
                AssemblyPlan.user_id == user_id,
                AssemblyPlan.status == "rendering",
                AssemblyPlan.current_revision_number == revision_number_value,
                AssemblyPlan.current_source_fingerprint == input_fingerprint_value,
            )
            .values(status="failed", updated_at=failed.updated_at)
        )
        await session.commit()
        raise


async def run_final_job_background(job_id: str, *, user_id: str) -> None:
    """Run a final job from a fresh session without surfacing worker errors to HTTP."""
    async with async_session_factory() as session:
        try:
            await run_final_job(session, job_id, user_id=user_id)
        except Exception:
            return


async def run_preview_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    """Execute one queued preview job and persist the controlled preview gate."""
    job = await _owned_job(session, job_id, user_id)
    if job.status != "queued":
        raise RenderJobConflictError("job_not_queued", status=job.status)
    plan = await _owned_plan(session, job.plan_id, user_id)
    revision = await _current_revision(session, plan)
    if plan.current_revision_number != job.revision_number or revision.version_number != job.revision_number:
        raise RenderRevisionConflictError(status=plan.status)
    if revision.source_fingerprint != job.input_fingerprint:
        raise RenderRevisionConflictError("source_fingerprint_conflict", status=plan.status)
    if plan.status != "preview_pending":
        raise RenderJobConflictError("preview_pending_required", status=plan.status)

    job.status = "running"
    job.attempt += 1
    started_at = utc_now()
    job.started_at = started_at
    job.updated_at = started_at
    await session.commit()

    output_path: Path | None = None
    try:
        timeline = json.loads(revision.timeline_json)
        if not isinstance(timeline, list):
            raise RenderJobConflictError("timeline_invalid", status=plan.status)
        project_root = _project_root(plan.project_name)
        relative_path, output_path = _artifact_path(project_root, job.id, job.revision_number)
        profile = json.loads(revision.output_profile_json)
        if not isinstance(profile, dict):
            profile = {}
        source_width = profile.get("width")
        source_height = profile.get("height")
        landscape = isinstance(source_width, int) and isinstance(source_height, int) and source_width > source_height
        width, height = (854, 480) if landscape else (480, 854)
        result = await render_preview_pipeline(
            timeline,
            audio=json.loads(revision.audio_json),
            subtitle=json.loads(revision.subtitle_json),
            packaging=json.loads(revision.packaging_json),
            project_root=project_root,
            output_path=output_path,
            width=width,
            height=height,
            fps=float(profile["fps"]) if isinstance(profile.get("fps"), (int, float)) else None,
        )
        if not output_path.is_file():
            raise RenderToolError("preview_output_missing", "preview output is missing")
        artifact = RenderArtifact(
            id=str(uuid.uuid4()),
            render_job_id=job.id,
            plan_id=plan.id,
            project_name=plan.project_name,
            user_id=user_id,
            revision_number=job.revision_number,
            kind="preview",
            relative_path=relative_path,
            mime_type="video/mp4",
            size_bytes=output_path.stat().st_size,
            duration_seconds=float(result["duration_seconds"]),
            width=int(result["width"]) if result.get("width") is not None else None,
            height=int(result["height"]) if result.get("height") is not None else None,
            fingerprint=file_fingerprint(output_path),
            created_at=utc_now(),
        )
        session.add(artifact)
        job.status = "succeeded"
        job.error_code = None
        job.error_message = None
        completed_at = utc_now()
        job.completed_at = completed_at
        job.updated_at = completed_at
        await media_assembly.mark_preview_ready(
            session,
            plan.id,
            user_id=user_id,
            revision_number=job.revision_number,
        )
        await session.commit()
        return await get_render_job(session, job.id, user_id=user_id)
    except Exception as exc:
        if output_path is not None:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        code, message = _safe_error(exc)
        await session.rollback()
        failed = await _owned_job(session, job.id, user_id)
        failed.status = "failed"
        failed.error_code = code
        failed.error_message = message
        failed_completed_at = utc_now()
        failed.completed_at = failed_completed_at
        failed.updated_at = failed_completed_at
        await session.commit()
        raise


async def run_preview_job_background(job_id: str, *, user_id: str) -> None:
    """Run a job from a fresh session, suitable for FastAPI BackgroundTasks."""
    async with async_session_factory() as session:
        try:
            await run_preview_job(session, job_id, user_id=user_id)
        except Exception:
            # The failure is already persisted on the job; background tasks must not
            # turn a completed HTTP response into an unhandled application error.
            return


async def get_render_artifact(session: AsyncSession, artifact_id: str, *, user_id: str) -> dict[str, Any]:
    artifact = await _owned_artifact(session, artifact_id, user_id)
    return _artifact_payload(artifact)


async def get_render_artifact_file(
    session: AsyncSession, artifact_id: str, *, user_id: str
) -> tuple[dict[str, Any], Path]:
    """Return artifact metadata and a path verified against its owner project."""
    artifact = await _owned_artifact(session, artifact_id, user_id)
    return _artifact_payload(artifact), resolve_artifact_file(artifact)


def resolve_artifact_file(artifact: RenderArtifact) -> Path:
    """Resolve a persisted artifact only inside its owning project directory."""
    project_root = _project_root(artifact.project_name)
    try:
        path = safe_join(project_root, artifact.relative_path, require_file=True)
    except (FileNotFoundError, PathTraversalError, TypeError, ValueError) as exc:
        raise RenderArtifactNotFoundError(artifact.id) from exc
    return path


async def _run_review_process(args: list[str], *, timeout_seconds: float = 120) -> tuple[bytes, bytes]:
    """Run ffprobe/ffmpeg with an argv list and bounded output for artifact review."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise FinalRenderReviewError("media_tools_unavailable", "media inspection tools are unavailable") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise FinalRenderReviewError("media_inspection_timeout", "media inspection timed out") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-2000:]
        raise FinalRenderReviewError("media_inspection_failed", detail or "media inspection failed")
    return stdout, stderr


def _final_artifact_relative_path(artifact: RenderArtifact, position: str) -> str:
    if position not in {"first", "middle", "last"}:
        raise ValueError("position must be first, middle, or last")
    return (Path("render_artifacts") / "reviews" / artifact.id / f"{position}.jpg").as_posix()


def _final_review_frame_path(artifact: RenderArtifact, position: str) -> Path:
    project_root = _project_root(artifact.project_name)
    relative = _final_artifact_relative_path(artifact, position)
    try:
        return safe_join(project_root, relative)
    except (PathTraversalError, TypeError, ValueError) as exc:
        raise RenderArtifactNotFoundError(artifact.id) from exc


async def _owned_final_artifact(session: AsyncSession, plan: AssemblyPlan, *, user_id: str) -> RenderArtifact:
    artifact = await session.scalar(
        select(RenderArtifact)
        .where(
            RenderArtifact.plan_id == plan.id,
            RenderArtifact.user_id == user_id,
            RenderArtifact.kind == "final",
            RenderArtifact.revision_number == plan.current_revision_number,
        )
        .order_by(RenderArtifact.created_at.desc())
    )
    if artifact is None:
        raise FinalRenderNotReadyError(plan.id)
    return artifact


async def _probe_final_artifact(path: Path) -> dict[str, Any]:
    ffprobe = resolve_tool("ffprobe")
    stdout, _ = await _run_review_process(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        payload = json.loads(stdout.decode("utf-8"))
        duration = float(payload["format"]["duration"])
        streams = payload.get("streams", [])
        video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        raise FinalRenderReviewError(
            "final_probe_invalid", "ffprobe returned an invalid final video description"
        ) from exc
    if duration <= 0:
        raise FinalRenderReviewError("final_probe_invalid", "final video duration must be positive")
    return {
        "duration_seconds": duration,
        "width": int(video_stream["width"]) if video_stream.get("width") is not None else None,
        "height": int(video_stream["height"]) if video_stream.get("height") is not None else None,
        "audio_stream_present": any(stream.get("codec_type") == "audio" for stream in streams),
    }


async def _detect_black_frames(path: Path) -> list[dict[str, float]]:
    ffmpeg = resolve_tool("ffmpeg")
    _, stderr = await _run_review_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.1:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    segments: list[dict[str, float]] = []
    pattern = re.compile(
        r"black_start:(?P<start>[0-9.]+).*?black_end:(?P<end>[0-9.]+).*?black_duration:(?P<duration>[0-9.]+)"
    )
    for match in pattern.finditer(stderr.decode("utf-8", errors="replace")):
        segments.append(
            {
                "start_seconds": float(match.group("start")),
                "end_seconds": float(match.group("end")),
                "duration_seconds": float(match.group("duration")),
            }
        )
    return segments


async def _detect_audio_metrics(path: Path) -> dict[str, float | int | None]:
    """Run deterministic FFmpeg loudness and peak analysis for a final artifact."""
    ffmpeg = resolve_tool("ffmpeg")
    _, stderr = await _run_review_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "volumedetect,ebur128=framelog=verbose",
            "-vn",
            "-f",
            "null",
            "-",
        ]
    )
    return parse_audio_metrics_log(stderr.decode("utf-8", errors="replace"))


async def _detect_silence_segments(path: Path) -> list[dict[str, float | None]]:
    ffmpeg = resolve_tool("ffmpeg")
    _, stderr = await _run_review_process(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-50dB:d=0.5",
            "-vn",
            "-f",
            "null",
            "-",
        ]
    )
    return parse_silencedetect_log(stderr.decode("utf-8", errors="replace"))


async def _extract_review_frame(
    artifact: RenderArtifact, source_path: Path, *, position: str, timestamp_seconds: float
) -> dict[str, Any]:
    ffmpeg = resolve_tool("ffmpeg")
    output_path = _final_review_frame_path(artifact, position)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await _run_review_process(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
    )
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise FinalRenderReviewError("review_frame_missing", f"could not extract {position} frame")
    return {
        "available": True,
        "position": position,
        "timestamp_seconds": timestamp_seconds,
        "relative_path": _final_artifact_relative_path(artifact, position),
    }


async def review_final_artifact(session: AsyncSession, plan_id: str, *, user_id: str) -> dict[str, Any]:
    """Inspect and persist the current revision's final artifact review."""
    plan = await _owned_plan(session, plan_id, user_id)
    artifact = await _owned_final_artifact(session, plan, user_id=user_id)
    revision = await _current_revision(session, plan)
    existing_snapshot = await session.scalar(
        select(RenderReviewSnapshot)
        .where(
            RenderReviewSnapshot.artifact_id == artifact.id,
            RenderReviewSnapshot.user_id == user_id,
            RenderReviewSnapshot.revision_number == revision.version_number,
            RenderReviewSnapshot.source_fingerprint == revision.source_fingerprint,
            RenderReviewSnapshot.artifact_fingerprint == artifact.fingerprint,
        )
        .order_by(RenderReviewSnapshot.created_at.desc())
    )
    if existing_snapshot is not None:
        checks = json.loads(existing_snapshot.checks_json)
        return {
            "status": existing_snapshot.status,
            "plan_id": plan.id,
            "revision_number": artifact.revision_number,
            "artifact": _artifact_payload(artifact),
            "checks": checks,
            "blocking_reasons": checks.get("blocking_reasons", []),
            "warning_reasons": checks.get("warning_reasons", []),
            "info_reasons": checks.get("info_reasons", []),
            "issues": checks.get("issues", []),
            "review_snapshot": _review_snapshot_payload(existing_snapshot),
        }
    source_path = resolve_artifact_file(artifact)
    probe = await _probe_final_artifact(source_path)
    black_segments = await _detect_black_frames(source_path)
    audio_present = bool(probe["audio_stream_present"])
    silence_segments = await _detect_silence_segments(source_path) if audio_present else []
    audio_metrics_error: str | None = None
    if audio_present:
        try:
            audio_metrics = await _detect_audio_metrics(source_path)
        except FinalRenderReviewError as exc:
            audio_metrics = {}
            audio_metrics_error = exc.code
    else:
        audio_metrics = {}
    duration = probe["duration_seconds"]
    timeline = json.loads(revision.timeline_json)
    subtitle = json.loads(revision.subtitle_json)
    frame_samples: list[dict[str, Any]] = []
    for position, timestamp_seconds in (
        ("first", 0.0),
        ("middle", duration / 2),
        ("last", max(0.0, duration - 0.001)),
    ):
        try:
            frame_samples.append(
                await _extract_review_frame(
                    artifact, source_path, position=position, timestamp_seconds=timestamp_seconds
                )
            )
        except FinalRenderReviewError as exc:
            if exc.code != "review_frame_missing":
                raise
            frame_samples.append(
                {
                    "available": False,
                    "position": position,
                    "timestamp_seconds": timestamp_seconds,
                    "error_code": exc.code,
                }
            )
    metadata_duration = artifact.duration_seconds
    duration_delta = duration - metadata_duration
    duration_check = {
        "seconds": duration,
        "metadata_seconds": metadata_duration,
        "within_metadata_tolerance": abs(duration_delta) <= 0.05,
    }
    packaging = json.loads(revision.packaging_json)
    expected_duration = expected_timeline_duration(timeline, packaging)
    timeline_delta = duration - expected_duration
    timeline_duration_check = {
        "expected_seconds": expected_duration,
        "actual_seconds": duration,
        "within_tolerance": abs(timeline_delta) <= 0.05,
    }
    audio_check = {
        "present": audio_present,
        "severity": "info" if not audio_present else None,
    }
    audio_quality = audio_quality_check(
        audio_stream_present=audio_present,
        silence_segments=silence_segments,
        duration_seconds=duration,
    )
    audio_levels = audio_level_check(audio_metrics)
    if audio_metrics_error is not None:
        audio_levels["analysis_error"] = audio_metrics_error
    black_check = classify_black_frame_edges(black_segments, duration_seconds=duration)
    subtitle_check = subtitle_bounds_check(subtitle, duration_seconds=duration)
    frames_check = {
        "all_available": all(frame.get("available", False) for frame in frame_samples),
        "items": frame_samples,
        "severity": None if all(frame.get("available", False) for frame in frame_samples) else "blocking",
    }
    checks = {
        "duration": duration_check,
        "timeline_duration": timeline_duration_check,
        "audio_stream": audio_check,
        "audio_quality": audio_quality,
        "audio_levels": audio_levels,
        "black_frames": black_check,
        "subtitle_bounds": subtitle_check,
        "frames": frames_check,
    }
    issues: list[dict[str, Any]] = []

    def add_issue(check: str, code: str, severity: str, **details: Any) -> None:
        issues.append({"check": check, "code": code, "severity": severity, **details})

    if not duration_check["within_metadata_tolerance"]:
        add_issue("duration", "duration_mismatch", "blocking", delta_seconds=duration_delta)
    if not timeline_duration_check["within_tolerance"]:
        add_issue("timeline_duration", "timeline_duration_mismatch", "blocking", delta_seconds=timeline_delta)
    if black_check["severity"] == "blocking":
        add_issue("black_frames", "black_frames_detected", "blocking")
    elif black_check["severity"] == "warning":
        add_issue("black_frames", "edge_black_frames_detected", "warning")
    if not subtitle_check["valid"]:
        add_issue("subtitle_bounds", "subtitle_bounds_invalid", "blocking")
    for issue in audio_quality.get("issues", []):
        add_issue("audio_quality", issue["code"], issue["severity"])
    for issue in audio_levels.get("issues", []):
        add_issue(
            "audio_levels",
            issue["code"],
            issue["severity"],
            **{key: value for key, value in issue.items() if key not in {"code", "severity"}},
        )
    if not audio_present:
        pass
    elif not audio_levels["available"]:
        add_issue("audio_levels", "audio_metrics_unavailable", "info")
    if not frames_check["all_available"]:
        add_issue("frames", "review_frame_missing", "blocking")

    blocking_reasons = [issue["code"] for issue in issues if issue["severity"] == "blocking"]
    warning_reasons = [issue["code"] for issue in issues if issue["severity"] == "warning"]
    info_reasons = [issue["code"] for issue in issues if issue["severity"] == "info"]
    status = "blocked" if blocking_reasons else "ready"
    checks_payload = {
        **checks,
        "issues": issues,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "info_reasons": info_reasons,
    }
    snapshot = RenderReviewSnapshot(
        id=str(uuid.uuid4()),
        artifact_id=artifact.id,
        plan_id=plan.id,
        project_name=plan.project_name,
        user_id=user_id,
        revision_number=revision.version_number,
        source_fingerprint=revision.source_fingerprint,
        artifact_fingerprint=artifact.fingerprint,
        status=status,
        checks_json=json.dumps(
            checks_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        created_at=utc_now(),
    )
    session.add(snapshot)
    await session.commit()
    return {
        "status": status,
        "plan_id": plan.id,
        "revision_number": artifact.revision_number,
        "artifact": _artifact_payload(artifact),
        "checks": checks_payload,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "info_reasons": info_reasons,
        "issues": issues,
        "review_snapshot": _review_snapshot_payload(snapshot),
    }


async def confirm_final_review(session: AsyncSession, artifact_id: str, *, user_id: str) -> dict[str, Any]:
    """Record authenticated user approval for the latest passing final review."""
    artifact = await _owned_artifact(session, artifact_id, user_id)
    if artifact.kind != "final":
        raise RenderReviewConflictError("final_artifact_required")
    plan = await _owned_plan(session, artifact.plan_id, user_id)
    revision = await _current_revision(session, plan)
    if revision.version_number != artifact.revision_number:
        raise RenderReviewConflictError("review_revision_conflict", status=plan.status)
    snapshot = await session.scalar(
        select(RenderReviewSnapshot)
        .where(
            RenderReviewSnapshot.artifact_id == artifact.id,
            RenderReviewSnapshot.user_id == user_id,
            RenderReviewSnapshot.revision_number == revision.version_number,
            RenderReviewSnapshot.source_fingerprint == revision.source_fingerprint,
            RenderReviewSnapshot.artifact_fingerprint == artifact.fingerprint,
        )
        .order_by(RenderReviewSnapshot.created_at.desc())
    )
    if snapshot is None:
        raise RenderReviewConflictError("review_required", status=plan.status)
    if snapshot.status != "ready":
        raise RenderReviewConflictError("review_blocked", status=snapshot.status)
    now = utc_now()
    snapshot.confirmed_by = user_id
    snapshot.confirmed_at = now
    await session.commit()
    return _review_snapshot_payload(snapshot)


async def get_final_review_frame_file(
    session: AsyncSession, artifact_id: str, *, position: str, user_id: str
) -> tuple[dict[str, Any], Path]:
    """Return an extracted final-review frame only for its owning user."""
    artifact = await _owned_artifact(session, artifact_id, user_id)
    if artifact.kind != "final":
        raise RenderArtifactNotFoundError(artifact_id)
    if position not in {"first", "middle", "last"}:
        raise RenderArtifactNotFoundError(artifact_id)
    path = _final_review_frame_path(artifact, position)
    if not path.is_file():
        raise RenderArtifactNotFoundError(artifact_id)
    return {"mime_type": "image/jpeg", "filename": path.name}, path


def _subtitle_cues_from_revision(value: object) -> list[Mapping[str, object]]:
    raw_cues: object = value
    if isinstance(value, dict):
        raw_cues = value.get("cues", [])
    if not isinstance(raw_cues, list):
        raise SubtitleExportError("subtitle configuration must contain a cues list")
    if not all(isinstance(cue, Mapping) for cue in raw_cues):
        raise SubtitleExportError("subtitle cues must be objects")
    return raw_cues


async def export_subtitles(session: AsyncSession, plan_id: str, *, format: str, user_id: str) -> dict[str, str]:
    """Serialize the current owned revision's validated subtitle cues for download."""
    if format not in {"srt", "vtt"}:
        raise SubtitleExportError("subtitle format must be srt or vtt")
    plan = await _owned_plan(session, plan_id, user_id)
    revision = await _current_revision(session, plan)
    try:
        subtitle_document = json.loads(revision.subtitle_json)
        cues = _subtitle_cues_from_revision(subtitle_document)
        content = generate_srt(cues) if format == "srt" else generate_vtt(cues)
    except (json.JSONDecodeError, SubtitleValidationError, TypeError) as exc:
        raise SubtitleExportError("subtitle configuration is invalid") from exc
    return {
        "content": content,
        "media_type": "application/x-subrip; charset=utf-8" if format == "srt" else "text/vtt; charset=utf-8",
        "filename": f"subtitles.{format}",
    }


__all__ = [
    "FinalRenderNotReadyError",
    "FinalRenderReviewError",
    "RenderArtifactNotFoundError",
    "RenderJobConflictError",
    "RenderJobNotFoundError",
    "RenderRevisionConflictError",
    "create_preview_job",
    "export_subtitles",
    "get_final_review_frame_file",
    "get_render_artifact",
    "get_render_artifact_file",
    "get_render_job",
    "list_render_jobs",
    "review_final_artifact",
    "resolve_artifact_file",
    "render_preview_pipeline",
    "render_final_pipeline",
    "retry_final_job",
    "retry_preview_job",
    "run_final_job",
    "run_final_job_background",
    "run_preview_job",
    "run_preview_job_background",
]
