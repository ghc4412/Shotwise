"""Immutable AssemblyPlanRevision export for Jianying-compatible draft packages."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lib.app_data_dir import app_data_dir
from lib.db.models.assembly_plan import AssemblyPlan, AssemblyPlanRevision
from lib.db.repositories.assembly_plan_repository import AssemblyPlanRepository
from lib.media_assembly.rendering import file_fingerprint
from lib.media_assembly.subtitles import SubtitleValidationError, generate_srt, generate_vtt
from lib.path_safety import PathTraversalError, safe_join
from lib.project_manager import ProjectManager
from server.services.media_assembly import AssemblyPlanConflictError, AssemblyPlanNotFoundError


class JianyingExportError(RuntimeError):
    """Raised when a revision cannot be exported safely."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class JianyingExportBundle:
    """A temporary ZIP and the directory that owns it."""

    path: Path
    revision_number: int
    temp_dir: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def _loads(raw: str, section: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JianyingExportError("revision_json_invalid", f"revision {section} is invalid") from exc


def _project_root(project_name: str) -> Path:
    return ProjectManager(app_data_dir()).get_project_path(project_name)


def _resolve_media(project_root: Path, source_ref: object) -> Path:
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise JianyingExportError("source_ref_invalid", "media source_ref must be a non-empty string")
    try:
        return safe_join(project_root, source_ref, require_file=True)
    except (FileNotFoundError, PathTraversalError, TypeError, ValueError) as exc:
        raise JianyingExportError(
            "source_file_missing", f"media source is unavailable: {source_ref}", status_code=409
        ) from exc


def _extension(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if suffix and len(suffix) <= 12 and suffix.replace(".", "").isalnum() else ".bin"


def _snapshot_expected_sha(snapshot: object, source_ref: str) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    items = snapshot.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        fingerprint = item.get("file_fingerprint")
        if isinstance(source, dict) and source.get("path") == source_ref and isinstance(fingerprint, dict):
            sha = fingerprint.get("sha256")
            return sha if isinstance(sha, str) and sha else None
    return None


def _copy_asset(
    source: Path,
    *,
    destination: Path,
    relative_path: str,
    source_ref: str,
    source_snapshot: object,
) -> dict[str, Any]:
    expected_sha = _snapshot_expected_sha(source_snapshot, source_ref)
    actual_sha = file_fingerprint(source)
    if expected_sha is not None and actual_sha != expected_sha:
        raise JianyingExportError(
            "source_fingerprint_conflict",
            f"media source has changed: {source_ref}",
            status_code=409,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "path": relative_path,
        "size_bytes": source.stat().st_size,
        "fingerprint": actual_sha,
    }


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _build_export(
    plan: AssemblyPlan,
    revision: AssemblyPlanRevision,
    *,
    project_root: Path,
) -> JianyingExportBundle:
    if plan.current_revision_number != revision.version_number:
        raise JianyingExportError("revision_conflict", "plan does not point to the requested revision", status_code=409)
    if plan.current_source_fingerprint != revision.source_fingerprint:
        raise JianyingExportError(
            "source_fingerprint_conflict", "revision source fingerprint is stale", status_code=409
        )

    timeline = _loads(revision.timeline_json, "timeline")
    audio = _loads(revision.audio_json, "audio")
    subtitle = _loads(revision.subtitle_json, "subtitle")
    packaging = _loads(revision.packaging_json, "packaging")
    snapshot = _loads(revision.source_snapshot_json, "source_snapshot")
    if (
        not isinstance(timeline, list)
        or not isinstance(audio, dict)
        or not isinstance(subtitle, dict)
        or not isinstance(packaging, dict)
    ):
        raise JianyingExportError("revision_shape_invalid", "revision sections have invalid shapes")

    temp_dir = Path(tempfile.mkdtemp(prefix="shotwise-jianying-"))
    timeline_export: list[dict[str, Any]] = []
    audio_export = dict(audio)
    audio_tracks = audio_export.get("tracks", [])
    if not isinstance(audio_tracks, list):
        audio_tracks = []
    audio_export["tracks"] = [dict(track) for track in audio_tracks if isinstance(track, dict)]
    packaging_export = dict(packaging)
    assets: list[dict[str, Any]] = []

    try:
        for index, raw_item in enumerate(timeline, start=1):
            if not isinstance(raw_item, dict):
                raise JianyingExportError("timeline_invalid", f"timeline item {index} is invalid")
            item = dict(raw_item)
            source_ref = item.get("source_ref")
            source = _resolve_media(project_root, source_ref)
            relative = Path("media") / f"{index:03d}-clip{_extension(source)}"
            asset = _copy_asset(
                source,
                destination=temp_dir / relative,
                relative_path=relative.as_posix(),
                source_ref=str(source_ref),
                source_snapshot=snapshot,
            )
            asset.update({"role": "video", "source_ref": str(source_ref), "timeline_index": index - 1})
            assets.append(asset)
            item["source_ref"] = relative.as_posix()
            item["media_path"] = relative.as_posix()
            timeline_export.append(item)

        for index, track in enumerate(audio_export["tracks"], start=1):
            source_ref = track.get("source_ref")
            source = _resolve_media(project_root, source_ref)
            relative = Path("media") / f"audio-{index:03d}{_extension(source)}"
            asset = _copy_asset(
                source,
                destination=temp_dir / relative,
                relative_path=relative.as_posix(),
                source_ref=str(source_ref),
                source_snapshot=snapshot,
            )
            asset.update({"role": "audio", "source_ref": str(source_ref), "audio_index": index - 1})
            assets.append(asset)
            track["source_ref"] = relative.as_posix()

        cover = packaging_export.get("cover")
        if isinstance(cover, dict) and cover.get("source_ref"):
            source_ref = cover["source_ref"]
            source = _resolve_media(project_root, source_ref)
            relative = Path("media") / f"cover{_extension(source)}"
            asset = _copy_asset(
                source,
                destination=temp_dir / relative,
                relative_path=relative.as_posix(),
                source_ref=str(source_ref),
                source_snapshot=snapshot,
            )
            asset.update({"role": "cover", "source_ref": str(source_ref)})
            assets.append(asset)
            cover = dict(cover)
            cover["source_ref"] = relative.as_posix()
            packaging_export["cover"] = cover

        cues = subtitle.get("cues", [])
        if not isinstance(cues, list):
            raise JianyingExportError("subtitle_invalid", "subtitle cues must be a list")
        try:
            srt = generate_srt(cues)
            vtt = generate_vtt(cues)
        except SubtitleValidationError as exc:
            raise JianyingExportError("subtitle_invalid", str(exc)) from exc

        timeline_path = temp_dir / "timeline.json"
        manifest = {
            "schema_version": "shotwise-jianying-draft/v1",
            "plan_id": plan.id,
            "revision_id": revision.id,
            "revision_number": revision.version_number,
            "source_fingerprint": revision.source_fingerprint,
            "assets": assets,
            "timeline": timeline_export,
            "audio": audio_export,
            "subtitle": {"cue_count": len(cues), "srt": "subtitles.srt", "vtt": "subtitles.vtt"},
            "packaging": packaging_export,
        }
        (temp_dir / "manifest.json").write_bytes(_json_bytes(manifest))
        timeline_path.write_bytes(_json_bytes(timeline_export))
        (temp_dir / "subtitles.srt").write_text(srt, encoding="utf-8")
        (temp_dir / "subtitles.vtt").write_text(vtt, encoding="utf-8")
        (temp_dir / "README.txt").write_text(
            "Shotwise Jianying draft package\n"
            f"Plan: {plan.id}\nRevision: {revision.version_number}\n"
            "This package uses relative media paths and is intended as an editable interchange package.\n",
            encoding="utf-8",
        )
        zip_path = temp_dir / f"shotwise-plan-{plan.id}-r{revision.version_number}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(temp_dir.rglob("*")):
                if file.is_file() and file != zip_path:
                    archive.write(file, file.relative_to(temp_dir).as_posix())
        return JianyingExportBundle(zip_path, revision.version_number, temp_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def export_current_revision(session: AsyncSession, plan_id: str, *, user_id: str) -> JianyingExportBundle:
    repository = AssemblyPlanRepository(session)
    plan = await repository.get_owned(plan_id, user_id=user_id)
    if plan is None:
        raise AssemblyPlanNotFoundError(plan_id)
    revision = await repository.get_current_revision(plan)
    if revision is None:
        raise AssemblyPlanConflictError("current_revision_missing", status=plan.status)
    return _build_export(plan, revision, project_root=_project_root(plan.project_name))


__all__ = ["JianyingExportBundle", "JianyingExportError", "export_current_revision"]
