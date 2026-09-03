"""File-backed adapters for the isolated draft-promotion workflow.

The adapter keeps promotion drafts outside the formal script files.  Formal script writes still
go through :class:`ProjectManager` and its existing validation/locking path; this module only
adds a durable review record and an atomic compare-and-write seam around that path.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, cast

import portalocker

from lib.app_data_dir import app_data_dir
from lib.json_io import atomic_write_json, load_json_or_none
from lib.project_manager import ProjectManager
from server.draft_promotion import (
    Draft,
    DraftOrigin,
    DraftPromotionRepository,
    DraftTarget,
    OfficialRevisionConflict,
    OfficialScript,
    PreparedPromotion,
    canonical_fingerprint,
)


class FileDraftPromotionRepository(DraftPromotionRepository):
    """Persist promotion records in an app-level JSON store.

    This is intentionally an adapter, not a second script store.  The formal script remains the
    only source of truth for production content, while the JSON file makes the review token and
    draft survive a request boundary without requiring a schema migration in the current phase.
    """

    def __init__(self, project_manager: ProjectManager, *, store_path: Path | None = None) -> None:
        self._project_manager = project_manager
        self._store_path = store_path or (app_data_dir() / ".draft_promotions.json")

    def read_official(self, target: DraftTarget) -> OfficialScript:
        path = self._script_path(target)
        if not path.exists():
            return OfficialScript(content={}, revision=0, fingerprint=canonical_fingerprint({}))
        content = self._project_manager.load_script(target.project_name, target.script_file)
        revision = path.stat().st_mtime_ns
        return OfficialScript(
            content=copy.deepcopy(content),
            revision=revision,
            fingerprint=canonical_fingerprint(content),
        )

    def load_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft | None:
        with self._locked_store(read_only=True) as store:
            raw = store.get(draft_id)
            if not isinstance(raw, dict):
                return None
            draft = _draft_from_dict(raw)
            return draft if actor_id is None or draft.actor_id == actor_id else None

    def list_drafts(self, target: DraftTarget, *, actor_id: str | None = None) -> list[Draft]:
        with self._locked_store(read_only=True) as store:
            drafts: list[Draft] = []
            for raw in store.values():
                if not isinstance(raw, dict):
                    continue
                try:
                    draft = _draft_from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    continue
                if draft.target == target and (actor_id is None or draft.actor_id == actor_id):
                    drafts.append(draft)
            return drafts

    def list_all(self, project_name: str, *, actor_id: str | None = None) -> list[Draft]:
        with self._locked_store(read_only=True) as store:
            drafts: list[Draft] = []
            for raw in store.values():
                if not isinstance(raw, dict):
                    continue
                try:
                    draft = _draft_from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    continue
                if draft.target.project_name == project_name and (actor_id is None or draft.actor_id == actor_id):
                    drafts.append(draft)
            return sorted(drafts, key=lambda draft: draft.id)

    def save_draft(self, draft: Draft) -> None:
        with self._locked_store() as store:
            store[draft.id] = _draft_to_dict(draft)

    def promote_atomically(
        self,
        target: DraftTarget,
        content: dict[str, Any],
        *,
        expected_revision: int,
        expected_fingerprint: str,
    ) -> OfficialScript:
        """Compare and write while holding the existing script lock."""

        normalized = self._project_manager.normalize_script_filename(target.script_file)
        path = self._script_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._project_manager.file_lock(path):
            if path.exists():
                script, _migrated = self._project_manager._read_script_unlocked(  # noqa: SLF001
                    target.project_name, normalized
                )
                current = self._official_from_loaded(target, script)
            else:
                script = {}
                current = OfficialScript(content={}, revision=0, fingerprint=canonical_fingerprint({}))
            if current.revision != expected_revision or current.fingerprint != expected_fingerprint:
                raise OfficialRevisionConflict(current)
            self._project_manager._write_script_unlocked(  # noqa: SLF001
                target.project_name,
                copy.deepcopy(content),
                normalized,
                validate=True,
                before=script if path.exists() else None,
            )

        return self.read_official(target)

    def _script_path(self, target: DraftTarget) -> Path:
        normalized = self._project_manager.normalize_script_filename(target.script_file)
        return self._project_manager.get_project_path(target.project_name) / "scripts" / normalized

    def _official_from_loaded(self, target: DraftTarget, content: dict[str, Any]) -> OfficialScript:
        return OfficialScript(
            content=copy.deepcopy(content),
            revision=self._script_path(target).stat().st_mtime_ns,
            fingerprint=canonical_fingerprint(content),
        )

    @contextmanager
    def _locked_store(self, *, read_only: bool = False) -> Iterator[dict[str, Any]]:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._store_path.with_name(f".{self._store_path.name}.lock")
        lock_path.touch(exist_ok=True)
        with portalocker.Lock(lock_path, flags=portalocker.LOCK_EX):
            raw = load_json_or_none(self._store_path)
            store = raw if isinstance(raw, dict) else {}
            yield store
            if not read_only:
                atomic_write_json(self._store_path, store)


def _draft_to_dict(draft: Draft) -> dict[str, Any]:
    payload = asdict(draft)
    if draft.prepared is not None:
        payload["prepared"] = asdict(draft.prepared)
    return payload


def _draft_from_dict(raw: dict[str, Any]) -> Draft:
    target = raw.get("target")
    if not isinstance(target, dict):
        raise ValueError("stored draft target is invalid")
    prepared_raw = raw.get("prepared")
    prepared = None
    if isinstance(prepared_raw, dict):
        prepared = PreparedPromotion(
            content=_object(prepared_raw.get("content")),
            expected_revision=int(prepared_raw["expected_revision"]),
            expected_fingerprint=str(prepared_raw["expected_fingerprint"]),
            confirmation_token=str(prepared_raw["confirmation_token"]),
            auto_merged_paths=tuple(str(item) for item in prepared_raw.get("auto_merged_paths", ())),
        )
    return Draft(
        id=str(raw["id"]),
        target=DraftTarget(project_name=str(target["project_name"]), script_file=str(target["script_file"])),
        content=_object(raw.get("content")),
        origin=cast("DraftOrigin", str(raw["origin"])),
        actor_id=str(raw["actor_id"]),
        base_content=_object(raw.get("base_content")),
        base_revision=int(raw["base_revision"]),
        base_fingerprint=str(raw["base_fingerprint"]),
        prepared=prepared,
        status=cast(Literal["active", "abandoned"], str(raw.get("status", "active"))),
    )


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("stored draft object is invalid")
    return copy.deepcopy(value)
