"""Index-only MediaAsset catalog.

MediaAsset gives existing SHOTWISE media stable IDs without changing any file.
The catalog never moves, renames, deletes, transcodes, or overwrites a media
file; legacy project JSON paths remain the compatibility contract.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from lib.feature_flags import feature_enabled

MediaKind = Literal["image", "video", "audio"]
MediaOrigin = Literal["upload", "generated", "edited", "extracted", "imported"]
BindingKind = Literal["project", "character", "scene", "prop", "product", "episode", "shot", "style", "final"]

_EXTENSIONS: dict[MediaKind, frozenset[str]] = {
    "image": frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"}),
    "video": frozenset({".mp4", ".mov", ".webm", ".mkv"}),
    "audio": frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg"}),
}


def media_index_enabled() -> bool:
    """Return whether optional MediaAsset registration is enabled."""

    return feature_enabled("media_asset_index")


def classify_media_path(path: str | Path) -> MediaKind | None:
    suffix = Path(path).suffix.lower()
    return next((kind for kind, extensions in _EXTENSIONS.items() if suffix in extensions), None)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class MediaAsset:
    id: str
    project_id: str
    kind: MediaKind
    original_name: str
    mime_type: str | None
    extension: str
    physical_path: str
    size_bytes: int
    fingerprint: str
    origin: MediaOrigin
    created_at: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    workflow_run_id: str | None = None
    workflow_node_key: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    prompt_snapshot: str | None = None
    archived: bool = False


@dataclass(frozen=True)
class MediaBinding:
    id: str
    media_asset_id: str
    project_id: str
    binding_kind: BindingKind
    target_id: str | None
    purpose: str
    created_at: str


@dataclass(frozen=True)
class MediaDerivation:
    id: str
    parent_media_asset_id: str
    child_media_asset_id: str
    operation: Literal["generated", "edited", "extracted", "composited"]
    created_at: str


@dataclass(frozen=True)
class MediaMigrationDiagnostic:
    project_id: str
    path: str
    code: Literal[
        "missing_file",
        "unsupported_media",
        "invalid_reference",
        "duplicate_file",
        "conflicting_file",
        "unreadable_file",
    ]
    detail: str
    created_at: str


@dataclass(frozen=True)
class MediaReconciliationItem:
    """A durable retry record for an index or binding operation."""

    id: str
    project_id: str
    relative_path: str
    workflow_run_id: str | None
    workflow_node_key: str | None
    reason: str
    created_at: str
    resolved_at: str | None = None
    origin: MediaOrigin = "imported"
    operation: str = "register"
    media_asset_id: str | None = None
    binding_kind: BindingKind | None = None
    target_id: str | None = None
    purpose: str | None = None
    parent_media_asset_id: str | None = None
    derivation_operation: Literal["generated", "edited", "extracted", "composited"] | None = None


class MediaAssetReferencedError(ValueError):
    """Raised when an indexed asset still has semantic references."""

    def __init__(self, media_asset_id: str, references: list[str]):
        self.media_asset_id = media_asset_id
        self.references = tuple(references)
        detail = ", ".join(references) if references else "unknown reference"
        super().__init__(f"MediaAsset is still referenced: {media_asset_id} ({detail})")


@dataclass
class _State:
    assets: dict[str, MediaAsset] = field(default_factory=dict)
    bindings: dict[str, MediaBinding] = field(default_factory=dict)
    derivations: dict[str, MediaDerivation] = field(default_factory=dict)
    diagnostics: list[MediaMigrationDiagnostic] = field(default_factory=list)
    reconciliation: list[MediaReconciliationItem] = field(default_factory=list)


class MediaCatalog:
    """Persistent index adapter with one file-based interface for callers."""

    def __init__(self, index_file: Path):
        self._index_file = index_file

    def _load(self) -> _State:
        if not self._index_file.exists():
            return _State()
        raw = json.loads(self._index_file.read_text(encoding="utf-8"))
        return _State(
            assets={
                key: MediaAsset(**{**value, "archived": value.get("archived", False)})
                for key, value in raw.get("assets", {}).items()
            },
            bindings={key: MediaBinding(**value) for key, value in raw.get("bindings", {}).items()},
            derivations={key: MediaDerivation(**value) for key, value in raw.get("derivations", {}).items()},
            diagnostics=[MediaMigrationDiagnostic(**value) for value in raw.get("diagnostics", [])],
            reconciliation=[MediaReconciliationItem(**value) for value in raw.get("reconciliation", [])],
        )

    def _save(self, state: _State) -> None:
        self._index_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "assets": {key: asdict(value) for key, value in state.assets.items()},
            "bindings": {key: asdict(value) for key, value in state.bindings.items()},
            "derivations": {key: asdict(value) for key, value in state.derivations.items()},
            "diagnostics": [asdict(value) for value in state.diagnostics],
            "reconciliation": [asdict(value) for value in state.reconciliation],
        }
        temporary = self._index_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self._index_file)

    def register(
        self,
        *,
        project_id: str,
        path: Path,
        origin: MediaOrigin,
        workflow_run_id: str | None = None,
        workflow_node_key: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        prompt_snapshot: str | None = None,
        original_name: str | None = None,
    ) -> MediaAsset | None:
        """Return an existing or newly indexed file without changing it."""

        state = self._load()
        kind = classify_media_path(path)
        if kind is None:
            state.diagnostics.append(
                MediaMigrationDiagnostic(project_id, str(path), "unsupported_media", "extension is not indexed", _now())
            )
            self._save(state)
            return None
        if not path.is_file():
            state.diagnostics.append(
                MediaMigrationDiagnostic(
                    project_id, str(path), "missing_file", "referenced file does not exist", _now()
                )
            )
            self._save(state)
            return None
        try:
            fingerprint = _fingerprint(path)
            size_bytes = path.stat().st_size
        except OSError as exc:
            state.diagnostics.append(
                MediaMigrationDiagnostic(
                    project_id,
                    str(path),
                    "unreadable_file",
                    f"cannot read file: {exc}",
                    _now(),
                )
            )
            self._save(state)
            return None
        for asset in state.assets.values():
            if asset.project_id != project_id:
                continue
            same_path = Path(asset.physical_path).resolve() == path.resolve()
            if same_path and asset.fingerprint == fingerprint:
                return asset
            if same_path:
                state.diagnostics.append(
                    MediaMigrationDiagnostic(
                        project_id,
                        str(path),
                        "conflicting_file",
                        f"the indexed path has different content ({asset.id})",
                        _now(),
                    )
                )
            elif asset.fingerprint == fingerprint:
                state.diagnostics.append(
                    MediaMigrationDiagnostic(
                        project_id,
                        str(path),
                        "duplicate_file",
                        f"same content is already indexed as {asset.id}",
                        _now(),
                    )
                )
        self._save(state) if state.diagnostics else None
        mime_type, _ = mimetypes.guess_type(path.name)
        asset = MediaAsset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            kind=kind,
            original_name=original_name or path.name,
            mime_type=mime_type,
            extension=path.suffix.lower(),
            physical_path=str(path),
            size_bytes=size_bytes,
            fingerprint=fingerprint,
            origin=origin,
            created_at=_now(),
            workflow_run_id=workflow_run_id,
            workflow_node_key=workflow_node_key,
            provider_id=provider_id,
            model_id=model_id,
            prompt_snapshot=prompt_snapshot,
        )
        state.assets[asset.id] = asset
        self._save(state)
        return asset

    def bind(
        self,
        media_asset_id: str,
        *,
        project_id: str,
        binding_kind: BindingKind,
        target_id: str | None,
        purpose: str,
    ) -> MediaBinding:
        state = self._load()
        asset = state.assets.get(media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise KeyError(f"unknown MediaAsset: {media_asset_id}")
        for binding in state.bindings.values():
            if (
                binding.media_asset_id,
                binding.project_id,
                binding.binding_kind,
                binding.target_id,
                binding.purpose,
            ) == (
                media_asset_id,
                project_id,
                binding_kind,
                target_id,
                purpose,
            ):
                return binding
        binding = MediaBinding(str(uuid.uuid4()), media_asset_id, project_id, binding_kind, target_id, purpose, _now())
        state.bindings[binding.id] = binding
        self._save(state)
        return binding

    def derive(
        self,
        parent_media_asset_id: str,
        child_media_asset_id: str,
        operation: Literal["generated", "edited", "extracted", "composited"],
    ) -> MediaDerivation:
        state = self._load()
        parent = state.assets.get(parent_media_asset_id)
        child = state.assets.get(child_media_asset_id)
        if parent is None or child is None:
            raise KeyError("both MediaAssets must exist")
        if parent.project_id != child.project_id:
            raise ValueError("MediaAssets must belong to the same project")
        for derivation in state.derivations.values():
            if (derivation.parent_media_asset_id, derivation.child_media_asset_id, derivation.operation) == (
                parent_media_asset_id,
                child_media_asset_id,
                operation,
            ):
                return derivation
        derivation = MediaDerivation(str(uuid.uuid4()), parent_media_asset_id, child_media_asset_id, operation, _now())
        state.derivations[derivation.id] = derivation
        self._save(state)
        return derivation

    def get(self, media_asset_id: str) -> MediaAsset | None:
        return self._load().assets.get(media_asset_id)

    def enqueue_reconciliation(
        self,
        *,
        project_id: str,
        relative_path: str,
        reason: str,
        workflow_run_id: str | None = None,
        workflow_node_key: str | None = None,
        origin: MediaOrigin = "imported",
        operation: str = "register",
        media_asset_id: str | None = None,
        binding_kind: BindingKind | None = None,
        target_id: str | None = None,
        purpose: str | None = None,
        parent_media_asset_id: str | None = None,
        derivation_operation: Literal["generated", "edited", "extracted", "composited"] | None = None,
    ) -> MediaReconciliationItem:
        """Persist a retry item without touching the generated file."""

        state = self._load()
        for existing in state.reconciliation:
            if existing.resolved_at is None and (
                existing.project_id,
                existing.relative_path,
                existing.workflow_run_id,
                existing.workflow_node_key,
                existing.operation,
                existing.media_asset_id,
                existing.binding_kind,
                existing.target_id,
                existing.purpose,
                existing.parent_media_asset_id,
                existing.derivation_operation,
            ) == (
                project_id,
                relative_path,
                workflow_run_id,
                workflow_node_key,
                operation,
                media_asset_id,
                binding_kind,
                target_id,
                purpose,
                parent_media_asset_id,
                derivation_operation,
            ):
                return existing
        item = MediaReconciliationItem(
            id=uuid.uuid4().hex,
            project_id=project_id,
            relative_path=relative_path,
            workflow_run_id=workflow_run_id,
            workflow_node_key=workflow_node_key,
            reason=reason[:500],
            created_at=_now(),
            origin=origin,
            operation=operation,
            media_asset_id=media_asset_id,
            binding_kind=binding_kind,
            target_id=target_id,
            purpose=purpose,
            parent_media_asset_id=parent_media_asset_id,
            derivation_operation=derivation_operation,
        )
        state.reconciliation.append(item)
        self._save(state)
        return item

    def reconciliation_items(self) -> list[MediaReconciliationItem]:
        """Return unresolved index repair items in creation order."""

        return [item for item in self._load().reconciliation if item.resolved_at is None]

    def resolve_reconciliation(self, *, operation: str, media_asset_id: str | None = None) -> int:
        """Mark matching durable repair records resolved after a successful retry."""

        state = self._load()
        resolved_at = _now()
        count = 0
        updated: list[MediaReconciliationItem] = []
        for item in state.reconciliation:
            if item.resolved_at is not None or item.operation != operation:
                updated.append(item)
                continue
            if media_asset_id is not None and item.media_asset_id != media_asset_id:
                updated.append(item)
                continue
            updated.append(replace(item, resolved_at=resolved_at))
            count += 1
        if count:
            state.reconciliation = updated
            self._save(state)
        return count

    def diagnostics(self) -> list[MediaMigrationDiagnostic]:
        """Return durable migration diagnostics in creation order."""

        return list(self._load().diagnostics)

    def record_diagnostic(
        self,
        *,
        project_id: str,
        path: str,
        code: str,
        detail: str,
    ) -> None:
        """Persist one idempotent diagnostic without touching the physical file."""

        state = self._load()
        identity = (project_id, path, code, detail)
        if any((item.project_id, item.path, item.code, item.detail) == identity for item in state.diagnostics):
            return
        state.diagnostics.append(
            MediaMigrationDiagnostic(
                project_id,
                path,
                code,  # type: ignore[arg-type]
                detail,
                _now(),
            )
        )
        self._save(state)

    async def sync_to_database(self, session: AsyncSession, *, project_id: str) -> dict[str, int]:
        """Mirror one JSON catalog into durable database rows.

        The JSON catalog remains the compatibility source of truth. This method
        is an explicit synchronization boundary and never touches physical files.
        """

        from lib.db.models.media_asset import (
            MediaAsset as MediaAssetRow,
        )
        from lib.db.models.media_asset import (
            MediaBinding as MediaBindingRow,
        )
        from lib.db.models.media_asset import (
            MediaDerivation as MediaDerivationRow,
        )

        state = self._load()
        assets = [asset for asset in state.assets.values() if asset.project_id == project_id]
        asset_ids = {asset.id for asset in assets}
        bindings = [binding for binding in state.bindings.values() if binding.project_id == project_id]
        derivations = [
            derivation
            for derivation in state.derivations.values()
            if derivation.parent_media_asset_id in asset_ids or derivation.child_media_asset_id in asset_ids
        ]

        # Synchronization is additive; partial scans must not delete durable references.

        asset_fields = (
            "project_id",
            "kind",
            "original_name",
            "mime_type",
            "extension",
            "physical_path",
            "size_bytes",
            "fingerprint",
            "origin",
            "created_at",
            "width",
            "height",
            "duration_seconds",
            "workflow_run_id",
            "workflow_node_key",
            "provider_id",
            "model_id",
            "prompt_snapshot",
            "archived",
        )
        binding_fields = ("media_asset_id", "project_id", "binding_kind", "target_id", "purpose", "created_at")
        derivation_fields = ("parent_media_asset_id", "child_media_asset_id", "operation", "created_at")

        for asset in assets:
            row = await session.get(MediaAssetRow, asset.id)
            if row is None:
                row = MediaAssetRow(id=asset.id)
                session.add(row)
            for field_name in asset_fields:
                setattr(row, field_name, getattr(asset, field_name))

        binding_fields = ("media_asset_id", "project_id", "binding_kind", "target_id", "purpose", "created_at")
        for binding in bindings:
            row = await session.get(MediaBindingRow, binding.id)
            if row is None:
                row = MediaBindingRow(id=binding.id)
                session.add(row)
            for field_name in binding_fields:
                setattr(row, field_name, getattr(binding, field_name))

        derivation_fields = ("parent_media_asset_id", "child_media_asset_id", "operation", "created_at")
        for derivation in derivations:
            row = await session.get(MediaDerivationRow, derivation.id)
            if row is None:
                row = MediaDerivationRow(id=derivation.id)
                session.add(row)
            for field_name in derivation_fields:
                setattr(row, field_name, getattr(derivation, field_name))

        await session.commit()
        return {"assets": len(assets), "bindings": len(bindings), "derivations": len(derivations)}

    def retry_reconciliation(self, *, project_root: Path, item_id: str | None = None) -> list[MediaAsset]:
        """Retry durable registration/binding work without deleting physical files."""

        repaired: list[MediaAsset] = []
        pending = self.reconciliation_items()
        if item_id is not None:
            pending = [item for item in pending if item.id == item_id]
        for item in pending:
            candidate = Path(item.relative_path)
            if candidate.is_absolute() or ".." in candidate.parts:
                continue
            asset = self.get(item.media_asset_id) if item.media_asset_id else None
            if asset is None:
                asset = self.register(
                    project_id=item.project_id,
                    path=project_root / candidate,
                    origin=item.origin,
                    workflow_run_id=item.workflow_run_id,
                    workflow_node_key=item.workflow_node_key,
                )
            if asset is None:
                continue
            try:
                if item.operation == "derivation" and item.parent_media_asset_id:
                    self.derive(
                        parent_media_asset_id=item.parent_media_asset_id,
                        child_media_asset_id=asset.id,
                        operation=item.derivation_operation or "generated",
                    )
                elif item.binding_kind is not None:
                    self.bind(
                        asset.id,
                        project_id=item.project_id,
                        binding_kind=item.binding_kind,
                        target_id=item.target_id,
                        purpose=item.purpose or "reconciled",
                    )
                elif item.operation == "binding" or item.reason.startswith("binding_failed:"):
                    self.bind(
                        asset.id,
                        project_id=item.project_id,
                        binding_kind="project",
                        target_id=None,
                        purpose="reconciled_output",
                    )
            except Exception:
                continue
            state = self._load()
            state.reconciliation = [
                replace(current, resolved_at=_now()) if current.id == item.id else current
                for current in state.reconciliation
            ]
            self._save(state)
            repaired.append(asset)
        return repaired

    def set_archived(self, media_asset_id: str, archived: bool) -> MediaAsset:
        state = self._load()
        asset = state.assets.get(media_asset_id)
        if asset is None:
            raise KeyError(media_asset_id)
        updated = replace(asset, archived=archived)
        state.assets[media_asset_id] = updated
        self._save(state)
        return updated

    def list_assets(
        self,
        *,
        project_id: str | None = None,
        kind: MediaKind | None = None,
        origin: MediaOrigin | None = None,
        workflow_run_id: str | None = None,
        archived: bool | None = None,
    ) -> list[MediaAsset]:
        """List indexed assets without touching or reorganizing physical files."""

        assets = self._load().assets.values()
        return sorted(
            (
                asset
                for asset in assets
                if (project_id is None or asset.project_id == project_id)
                and (kind is None or asset.kind == kind)
                and (origin is None or asset.origin == origin)
                and (workflow_run_id is None or asset.workflow_run_id == workflow_run_id)
                and (archived is None or asset.archived == archived)
            ),
            key=lambda asset: (asset.created_at, asset.id),
            reverse=True,
        )

    def delete(self, media_asset_id: str) -> MediaAsset:
        """Remove an index row only after all semantic references are gone."""

        state = self._load()
        asset = state.assets.get(media_asset_id)
        if asset is None:
            raise KeyError(media_asset_id)
        references = [
            f"binding:{binding.id}" for binding in state.bindings.values() if binding.media_asset_id == media_asset_id
        ]
        references.extend(
            f"derivation:{derivation.id}"
            for derivation in state.derivations.values()
            if media_asset_id in {derivation.parent_media_asset_id, derivation.child_media_asset_id}
        )
        if asset.workflow_run_id:
            references.append(f"workflow_run:{asset.workflow_run_id}")
        if references:
            raise MediaAssetReferencedError(media_asset_id, references)
        del state.assets[media_asset_id]
        self._save(state)
        return asset

    def bindings_for(self, media_asset_id: str) -> list[MediaBinding]:
        return [item for item in self._load().bindings.values() if item.media_asset_id == media_asset_id]

    def derivations_for(self, media_asset_id: str) -> list[MediaDerivation]:
        return [
            item
            for item in self._load().derivations.values()
            if item.parent_media_asset_id == media_asset_id or item.child_media_asset_id == media_asset_id
        ]

    def backfill(self, *, project_id: str, project_root: Path, relative_paths: Iterable[str]) -> list[MediaAsset]:
        """Index legacy references idempotently and report unsafe references."""

        indexed: list[MediaAsset] = []
        for relative_path in relative_paths:
            candidate = Path(relative_path)
            if candidate.is_absolute() or ".." in candidate.parts:
                state = self._load()
                state.diagnostics.append(
                    MediaMigrationDiagnostic(
                        project_id, relative_path, "invalid_reference", "path escapes project root", _now()
                    )
                )
                self._save(state)
                continue
            asset = self.register(project_id=project_id, path=project_root / candidate, origin="imported")
            if asset is not None:
                indexed.append(asset)
        return indexed


def project_media_catalog(project_root: Path) -> MediaCatalog:
    return MediaCatalog(project_root / ".media-assets.json")
