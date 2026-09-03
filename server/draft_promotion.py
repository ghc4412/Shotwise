from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from secrets import token_urlsafe
from typing import Literal, Protocol, cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]
type DraftOrigin = Literal["agent", "upload", "online_ai"]
type DraftStatus = Literal["active", "abandoned"]


@dataclass(frozen=True, slots=True)
class DraftTarget:
    """The formal script a draft is intended to change."""

    project_name: str
    script_file: str


@dataclass(frozen=True, slots=True)
class OfficialScript:
    """A snapshot supplied by the repository adapter's formal-script seam."""

    content: JsonObject
    revision: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DraftValidationIssue:
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True, slots=True)
class PromotionConflict:
    """A three-way merge conflict expressed as a JSON Pointer path."""

    path: str
    base_value: JsonValue | None
    current_value: JsonValue | None
    draft_value: JsonValue | None


@dataclass(frozen=True, slots=True)
class PreparedPromotion:
    """A reviewed promotion plan bound to one official-script revision."""

    content: JsonObject
    expected_revision: int
    expected_fingerprint: str
    confirmation_token: str
    auto_merged_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Draft:
    id: str
    target: DraftTarget
    content: JsonObject
    origin: DraftOrigin
    actor_id: str
    base_content: JsonObject
    base_revision: int
    base_fingerprint: str
    prepared: PreparedPromotion | None = None
    status: DraftStatus = "active"


@dataclass(frozen=True, slots=True)
class PromotionPreparation:
    """Result of validation plus optimistic-concurrency comparison."""

    status: Literal["invalid", "conflicted", "ready_for_confirmation"]
    validation_issues: tuple[DraftValidationIssue, ...] = ()
    conflicts: tuple[PromotionConflict, ...] = ()
    auto_merged_paths: tuple[str, ...] = ()
    confirmation_token: str | None = None
    preview_content: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class PromotionResult:
    status: Literal["promoted", "invalid", "stale_confirmation", "invalid_confirmation"]
    validation_issues: tuple[DraftValidationIssue, ...] = ()
    promoted_revision: int | None = None


class OfficialRevisionConflict(Exception):
    """Raised by an adapter when its atomic compare-and-write detects a change."""

    def __init__(self, current: OfficialScript) -> None:
        self.current = current
        super().__init__(f"official script changed at revision {current.revision}")


class DraftPromotionRepository(Protocol):
    """Repository seam for durable drafts and atomic official-script promotion.

    ``promote_atomically`` must compare the provided revision and fingerprint
    with the current official script in the same critical section as its write.
    """

    def read_official(self, target: DraftTarget) -> OfficialScript: ...

    def load_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft | None: ...

    def list_drafts(self, target: DraftTarget, *, actor_id: str | None = None) -> list[Draft]: ...

    def save_draft(self, draft: Draft) -> None: ...

    def promote_atomically(
        self,
        target: DraftTarget,
        content: JsonObject,
        *,
        expected_revision: int,
        expected_fingerprint: str,
    ) -> OfficialScript: ...


type DraftValidator = Callable[[object], Sequence[DraftValidationIssue]]


def canonical_fingerprint(content: JsonObject) -> str:
    """Return a stable JSON fingerprint for optimistic concurrency checks."""

    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _validate_json_object(content: object) -> Sequence[DraftValidationIssue]:
    """Baseline validation; integrations inject the project's script validator."""

    if not isinstance(content, dict):
        return (DraftValidationIssue("draft_not_object", "Draft content must be a JSON object."),)
    return ()


class DraftPromotionService:
    """Deep module for validated, reviewed, atomic formal-script promotion.

    Its public interface has three operations:
    ``create`` snapshots the existing formal script; ``prepare_promotion``
    validates and three-way merges; and ``confirm_promotion`` revalidates then
    asks the repository to atomically compare-and-write the reviewed result.
    """

    def __init__(
        self,
        repository: DraftPromotionRepository,
        *,
        validator: DraftValidator = _validate_json_object,
        id_factory: Callable[[], str] = lambda: token_urlsafe(18),
        token_factory: Callable[[], str] = lambda: token_urlsafe(24),
    ) -> None:
        self._repository = repository
        self._validator = validator
        self._id_factory = id_factory
        self._token_factory = token_factory

    def create(
        self,
        *,
        target: DraftTarget,
        content: JsonObject,
        origin: DraftOrigin,
        actor_id: str,
    ) -> Draft:
        """Create a draft from Agent, upload, or online-AI output."""

        official = self._repository.read_official(target)
        draft = Draft(
            id=self._id_factory(),
            target=target,
            content=deepcopy(content),
            origin=origin,
            actor_id=actor_id,
            base_content=deepcopy(official.content),
            base_revision=official.revision,
            base_fingerprint=official.fingerprint,
        )
        self._repository.save_draft(draft)
        return draft

    def update(self, draft_id: str, *, content: JsonObject, actor_id: str | None = None) -> Draft:
        """Replace an active draft without changing its review baseline."""

        draft = self._require_active_draft(draft_id, actor_id=actor_id)
        updated = replace(draft, content=deepcopy(content), prepared=None)
        self._repository.save_draft(updated)
        return updated

    def abandon(self, draft_id: str, *, actor_id: str | None = None) -> Draft:
        """Mark a draft abandoned while retaining its audit record."""

        draft = self._require_draft(draft_id, actor_id=actor_id)
        if draft.status == "abandoned":
            return draft
        abandoned = replace(draft, status="abandoned", prepared=None)
        self._repository.save_draft(abandoned)
        return abandoned

    def list_drafts(self, *, target: DraftTarget, actor_id: str | None = None) -> list[Draft]:
        """List drafts for one project, ordered deterministically by id."""

        return sorted(self._repository.list_drafts(target, actor_id=actor_id), key=lambda draft: draft.id)

    def prepare_promotion(self, draft_id: str, *, actor_id: str | None = None) -> PromotionPreparation:
        """Validate a draft and produce either conflicts or a confirmation token."""

        draft = self._require_draft(draft_id, actor_id=actor_id)
        if draft.status != "active":
            return PromotionPreparation(
                status="invalid",
                validation_issues=(DraftValidationIssue("draft_abandoned", "Draft has been abandoned."),),
            )
        validation_issues = tuple(self._validator(deepcopy(draft.content)))
        if validation_issues:
            self._repository.save_draft(replace(draft, prepared=None))
            return PromotionPreparation(status="invalid", validation_issues=validation_issues)

        current = self._repository.read_official(draft.target)
        candidate = deepcopy(draft.content)
        auto_merged_paths: tuple[str, ...] = ()
        if current.revision != draft.base_revision or current.fingerprint != draft.base_fingerprint:
            merge = _three_way_merge(draft.base_content, current.content, draft.content)
            if merge.conflicts:
                self._repository.save_draft(replace(draft, prepared=None))
                return PromotionPreparation(status="conflicted", conflicts=merge.conflicts)
            candidate = merge.content
            auto_merged_paths = merge.auto_merged_paths

        prepared = PreparedPromotion(
            content=candidate,
            expected_revision=current.revision,
            expected_fingerprint=current.fingerprint,
            confirmation_token=self._token_factory(),
            auto_merged_paths=auto_merged_paths,
        )
        self._repository.save_draft(replace(draft, prepared=prepared))
        return PromotionPreparation(
            status="ready_for_confirmation",
            auto_merged_paths=prepared.auto_merged_paths,
            confirmation_token=prepared.confirmation_token,
            preview_content=deepcopy(prepared.content),
        )

    def confirm_promotion(
        self, draft_id: str, *, confirmation_token: str, actor_id: str | None = None
    ) -> PromotionResult:
        """Revalidate and atomically promote a previously reviewed draft."""

        draft = self._require_draft(draft_id, actor_id=actor_id)
        if draft.status != "active":
            return PromotionResult(status="invalid_confirmation")
        prepared = draft.prepared
        if prepared is None or confirmation_token != prepared.confirmation_token:
            return PromotionResult(status="invalid_confirmation")

        validation_issues = tuple(self._validator(deepcopy(prepared.content)))
        if validation_issues:
            self._repository.save_draft(replace(draft, prepared=None))
            return PromotionResult(status="invalid", validation_issues=validation_issues)

        try:
            promoted = self._repository.promote_atomically(
                draft.target,
                deepcopy(prepared.content),
                expected_revision=prepared.expected_revision,
                expected_fingerprint=prepared.expected_fingerprint,
            )
        except OfficialRevisionConflict:
            self._repository.save_draft(replace(draft, prepared=None))
            return PromotionResult(status="stale_confirmation")

        self._repository.save_draft(replace(draft, prepared=None))
        return PromotionResult(status="promoted", promoted_revision=promoted.revision)

    def _require_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft:
        draft = self._repository.load_draft(draft_id, actor_id=actor_id)
        if draft is None:
            raise KeyError(f"draft not found: {draft_id}")
        return draft

    def _require_active_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft:
        draft = self._require_draft(draft_id, actor_id=actor_id)
        if draft.status != "active":
            raise ValueError("draft is abandoned")
        return draft

    def get_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft:
        """Return a draft through the same repository seam used by promotion."""

        return self._require_draft(draft_id, actor_id=actor_id)


@dataclass(frozen=True, slots=True)
class _MergeResult:
    content: JsonObject
    conflicts: tuple[PromotionConflict, ...]
    auto_merged_paths: tuple[str, ...]


def _three_way_merge(base: JsonObject, current: JsonObject, draft: JsonObject) -> _MergeResult:
    merged, conflicts, paths = _merge_value(base, current, draft, "")
    if not isinstance(merged, dict):
        raise AssertionError("top-level promotion content must remain a JSON object")
    return _MergeResult(merged, tuple(conflicts), tuple(paths))


_MISSING = object()


def _merge_value(
    base: JsonValue | object,
    current: JsonValue | object,
    draft: JsonValue | object,
    path: str,
) -> tuple[JsonValue | object, list[PromotionConflict], list[str]]:
    if draft == base:
        paths: list[str] = []
        if current != base:
            paths.append(_display_path(path))
        return deepcopy(current), [], paths
    if current == base:
        return deepcopy(draft), [], []
    if current == draft:
        return deepcopy(current), [], []

    if isinstance(base, dict) and isinstance(current, dict) and isinstance(draft, dict):
        merged: dict[str, JsonValue] = {}
        conflicts: list[PromotionConflict] = []
        auto_merged_paths: list[str] = []
        for key in sorted(set(base) | set(current) | set(draft)):
            item, item_conflicts, item_paths = _merge_value(
                base.get(key, _MISSING),
                current.get(key, _MISSING),
                draft.get(key, _MISSING),
                _json_pointer(path, key),
            )
            conflicts.extend(item_conflicts)
            auto_merged_paths.extend(item_paths)
            if item is not _MISSING:
                merged[key] = item  # type: ignore[assignment]
        return merged, conflicts, auto_merged_paths

    if isinstance(base, list) and isinstance(current, list) and isinstance(draft, list):
        return _merge_array(base, current, draft, path)

    return (
        _MISSING,
        [
            PromotionConflict(
                path=_display_path(path),
                base_value=None if base is _MISSING else deepcopy(base),  # type: ignore[arg-type]
                current_value=None if current is _MISSING else deepcopy(current),  # type: ignore[arg-type]
                draft_value=None if draft is _MISSING else deepcopy(draft),  # type: ignore[arg-type]
            )
        ],
        [],
    )


_STABLE_ID_FIELDS = {"scenes": "scene_id", "segments": "segment_id", "shots": "shot_id", "video_units": "unit_id"}


def _merge_array(
    base: list[JsonValue], current: list[JsonValue], draft: list[JsonValue], path: str
) -> tuple[JsonValue | object, list[PromotionConflict], list[str]]:
    """Merge known script collections by stable id; treat other arrays atomically."""

    field = path.rsplit("/", 1)[-1] if path else ""
    id_field = _STABLE_ID_FIELDS.get(field)
    if id_field is None:
        return (
            _MISSING,
            [
                PromotionConflict(
                    path=_display_path(path),
                    base_value=deepcopy(base),
                    current_value=deepcopy(current),
                    draft_value=deepcopy(draft),
                )
            ],
            [],
        )

    indexed = [_index_stable_array(items, id_field) for items in (base, current, draft)]
    if any(index is None for index in indexed):
        return (
            _MISSING,
            [
                PromotionConflict(
                    path=_display_path(path),
                    base_value=deepcopy(base),
                    current_value=deepcopy(current),
                    draft_value=deepcopy(draft),
                )
            ],
            [],
        )

    base_by_id = cast(dict[str, JsonObject], indexed[0])
    current_by_id = cast(dict[str, JsonObject], indexed[1])
    draft_by_id = cast(dict[str, JsonObject], indexed[2])
    base_ids = list(base_by_id)
    current_ids = list(current_by_id)
    draft_ids = list(draft_by_id)
    current_order_changed = _relative_order_changed(base_ids, current_ids)
    draft_order_changed = _relative_order_changed(base_ids, draft_ids)
    if (
        current_order_changed
        and draft_order_changed
        and _relative_order(base_ids, current_ids) != _relative_order(base_ids, draft_ids)
    ):
        return (
            _MISSING,
            [
                PromotionConflict(
                    path=_display_path(path),
                    base_value=deepcopy(base),
                    current_value=deepcopy(current),
                    draft_value=deepcopy(draft),
                )
            ],
            [],
        )

    merged_by_id: dict[str, JsonValue] = {}
    conflicts: list[PromotionConflict] = []
    auto_merged_paths: list[str] = []
    all_ids = dict.fromkeys(base_ids + current_ids + draft_ids)
    for item_id in all_ids:
        item, item_conflicts, item_paths = _merge_value(
            base_by_id.get(item_id, _MISSING),
            current_by_id.get(item_id, _MISSING),
            draft_by_id.get(item_id, _MISSING),
            f"{path}/{_escape_pointer_segment(item_id)}",
        )
        conflicts.extend(item_conflicts)
        auto_merged_paths.extend(item_paths)
        if item is not _MISSING:
            merged_by_id[item_id] = cast(JsonValue, item)

    if conflicts:
        return _MISSING, conflicts, auto_merged_paths

    if draft_order_changed and not current_order_changed:
        preferred_order = draft_ids
    else:
        preferred_order = current_ids
    merged_order = list(dict.fromkeys(preferred_order + current_ids + draft_ids + base_ids))
    return [merged_by_id[item_id] for item_id in merged_order if item_id in merged_by_id], [], auto_merged_paths


def _index_stable_array(items: list[JsonValue], id_field: str) -> dict[str, JsonObject] | None:
    indexed: dict[str, JsonObject] = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        raw_id = item.get(id_field)
        if not isinstance(raw_id, str) or not raw_id or raw_id in indexed:
            return None
        indexed[raw_id] = item
    return indexed


def _relative_order_changed(base_ids: list[str], candidate_ids: list[str]) -> bool:
    common = set(base_ids) & set(candidate_ids)
    if not common:
        return False
    base_order = [item_id for item_id in base_ids if item_id in common]
    candidate_order = [item_id for item_id in candidate_ids if item_id in common]
    return base_order != candidate_order


def _relative_order(base_ids: list[str], candidate_ids: list[str]) -> list[str]:
    common = set(base_ids) & set(candidate_ids)
    return [item_id for item_id in candidate_ids if item_id in common]


def _json_pointer(parent: str, key: str) -> str:
    return f"{parent}/{_escape_pointer_segment(key)}"


def _escape_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _display_path(path: str) -> str:
    return path or "/"
