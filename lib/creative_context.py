"""Fail-closed resolution of Creative Board creation context.

Natural-language references are resolved only against explicit project and
board candidates. A reference must have exactly one stable-ID match before it
can enter the gated creation-context resolver.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lib.creation_skills import (
    OFFICIAL_CREATION_SKILLS,
    CreationSkillDefinition,
    compatibility_report,
    list_official_creation_skills,
)

_RESOURCE_INPUTS = {
    "document": "document",
    "brief": "brief",
    "image": "image",
    "media_asset": "media_asset",
    "media_image": "image",
    "character": "image",
    "scene": "image",
    "prop": "image",
    "product": "image",
    "video": "video",
    "audio": "audio",
    "shot": "image",
    "storyboard": "image",
}
_MEDIA_RESOURCE_TYPES = frozenset({"image", "media_image", "media_asset", "video", "audio"})
_APPROVED_STATUSES = frozenset({"approved", "confirmed", "passed", "succeeded"})
_PREVIEWED_PLAN_STATUSES = frozenset({"previewed", "confirmed", "started", "running", "succeeded"})


class CreativeContextResolutionError(ValueError):
    """Raised when context cannot be resolved to unambiguous resource IDs."""

    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None):
        self.code = code
        self.details = dict(details or {})
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SelectedResource:
    id: str
    resource_type: str


@dataclass(frozen=True, slots=True)
class ContextReference:
    """A user-facing reference that must resolve to stable project IDs."""

    text: str
    expected_type: str | None = None


def _value(record: object, key: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _decoded(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _mapping(value: object) -> Mapping[str, object] | None:
    decoded = _decoded(value)
    return decoded if isinstance(decoded, Mapping) else None


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _skill_by_id(skill_id: str) -> CreationSkillDefinition:
    for skill in OFFICIAL_CREATION_SKILLS:
        if skill.id == skill_id:
            return skill
    raise CreativeContextResolutionError("unknown_creation_skill", details={"skill_id": skill_id})


def _ids(records: object, field: str) -> set[str]:
    if isinstance(records, Mapping):
        values = records.values()
    else:
        values = _sequence(records)
    result: set[str] = set()
    for record in values:
        if isinstance(record, (str, int)):
            result.add(str(record))
            continue
        identifier = _value(record, "id") or _value(record, f"{field}_id") or _value(record, field)
        if identifier is not None:
            result.add(str(identifier))
    return result


def _project_entities(project: Mapping[str, object], field: str) -> object:
    return project.get(field, project.get(f"{field}s"))


def _validate_project_id(project_id: str, project: Mapping[str, object]) -> None:
    declared = _value(project, "id") or _value(project, "project_id")
    if declared is not None and str(declared) != project_id:
        raise CreativeContextResolutionError(
            "project_context_mismatch",
            details={"project_id": project_id, "declared_project_id": str(declared)},
        )


def _validate_episode_and_shot(project: Mapping[str, object], episode_id: str | None, shot_id: str | None) -> None:
    if shot_id and not episode_id:
        raise CreativeContextResolutionError("episode_id_required_for_shot", details={"shot_id": shot_id})
    episodes = _project_entities(project, "episode")
    if episode_id and episodes is not None and episode_id not in _ids(episodes, "episode"):
        raise CreativeContextResolutionError("episode_not_found", details={"episode_id": episode_id})
    shots = _project_entities(project, "shot")
    if shots is None and episodes is not None:
        nested: list[object] = []
        for episode in episodes.values() if isinstance(episodes, Mapping) else _sequence(episodes):
            raw = _value(episode, "shots", _value(episode, "shot", ()))
            nested.extend(raw.values() if isinstance(raw, Mapping) else _sequence(raw))
        shots = nested
    if shot_id and shots is not None and shot_id not in _ids(shots, "shot"):
        raise CreativeContextResolutionError("shot_not_found", details={"shot_id": shot_id, "episode_id": episode_id})


def _validate_board(
    project_id: str,
    board_id: str | None,
    board: Mapping[str, object] | None,
    selected: Sequence[dict[str, str]],
    board_items: Sequence[object],
) -> None:
    if not board_id or not board_id.strip():
        raise CreativeContextResolutionError("creative_board_id_required")
    if board is None:
        return
    declared_id = _value(board, "id") or _value(board, "creative_board_id")
    if declared_id is not None and str(declared_id) != board_id:
        raise CreativeContextResolutionError("creative_board_context_mismatch", details={"creative_board_id": board_id})
    declared_project = _value(board, "project_id")
    if declared_project is not None and str(declared_project) != project_id:
        raise CreativeContextResolutionError("creative_board_project_mismatch", details={"project_id": project_id})
    if not board_items and "items" in board:
        board_items = _sequence(board.get("items"))
    for resource in selected:
        matches = [
            item
            for item in board_items
            if str(_value(item, "resource_id", "")) == resource["id"] or str(_value(item, "id", "")) == resource["id"]
        ]
        if not matches:
            raise CreativeContextResolutionError(
                "resource_not_on_creative_board",
                details={"creative_board_id": board_id, "resource_id": resource["id"]},
            )
        if len(matches) > 1:
            raise CreativeContextResolutionError(
                "ambiguous_board_resource",
                details={"creative_board_id": board_id, "resource_id": resource["id"]},
            )


def _validate_media_assets(
    project: Mapping[str, object], selected: Sequence[dict[str, str]], media_assets: object
) -> None:
    source = media_assets if media_assets is not None else project.get("media_assets")
    if source is None:
        return
    if isinstance(source, Mapping):
        by_id = {str(key): value for key, value in source.items()}
    else:
        by_id = {str(_value(asset, "id")): asset for asset in _sequence(source) if _value(asset, "id") is not None}
    for resource in selected:
        if resource["resource_type"] not in _MEDIA_RESOURCE_TYPES:
            continue
        asset = by_id.get(resource["id"])
        if asset is None:
            raise CreativeContextResolutionError("media_asset_not_found", details={"media_asset_id": resource["id"]})
        kind = str(_value(asset, "kind", _value(asset, "media_kind", ""))).lower()
        expected = {"video": "video", "audio": "audio"}.get(resource["resource_type"], "image")
        if kind and resource["resource_type"] != "media_asset" and kind != expected:
            raise CreativeContextResolutionError(
                "media_asset_kind_mismatch", details={"media_asset_id": resource["id"]}
            )


def _plan_skill_id(plan: object) -> str | None:
    skill_id = _value(plan, "skill_id")
    if skill_id:
        return str(skill_id)
    version_id = str(_value(plan, "creation_skill_version_id", ""))
    return version_id.split(":", 1)[0] if version_id else None


def _plan_snapshot(plan: object) -> Mapping[str, object] | None:
    for key in ("project_snapshot", "project_context", "project_snapshot_json"):
        snapshot = _mapping(_value(plan, key))
        if snapshot is not None:
            return snapshot
    return None


def _plan_resource_ids(plan: object) -> set[str]:
    raw = _value(plan, "resource_ids", _value(plan, "resource_ids_json", ()))
    decoded = _decoded(raw)
    if isinstance(decoded, Mapping):
        decoded = decoded.get("resource_ids", ())
    return {str(_value(item, "id", item)) for item in _sequence(decoded)}


def _plan_previewed(plan: object, explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    if bool(_value(plan, "previewed", False)):
        return True
    if str(_value(plan, "status", "")).lower() in _PREVIEWED_PLAN_STATUSES:
        return True
    return _value(plan, "preview", None) is not None or _value(plan, "preview_json", None) is not None


def _gate(value: object) -> tuple[bool | None, bool]:
    value = _decoded(value)
    if isinstance(value, Mapping):
        required = bool(value.get("required", value.get("enabled", False)))
        result = value.get("passed", value.get("ok"))
        return (bool(result) if result is not None else None), required
    if isinstance(value, bool):
        return value, True
    if isinstance(value, str):
        return value.lower() in _APPROVED_STATUSES, True
    return None, False


def _validate_plan_and_gates(
    *,
    project_id: str,
    project: Mapping[str, object],
    selected: Sequence[dict[str, str]],
    current_skill_id: str | None,
    creation_plan_id: str | None,
    creation_plan: object,
    workflow_run_id: str | None,
    workflow_run: object,
    previewed: bool | None,
    confirmed: bool,
    quality_gate_passed: bool | None,
    approval_status: str | None,
    allow_gate_bypass: bool,
    requested_generation_mode: str | None,
) -> tuple[str | None, dict[str, object]]:
    if not creation_plan_id or not creation_plan_id.strip():
        raise CreativeContextResolutionError("creation_plan_required")
    if allow_gate_bypass:
        raise CreativeContextResolutionError("gate_bypass_forbidden")
    if creation_plan is None:
        raise CreativeContextResolutionError(
            "creation_plan_details_required", details={"creation_plan_id": creation_plan_id}
        )
    plan_id = _value(creation_plan, "id", _value(creation_plan, "plan_id"))
    if plan_id is not None and str(plan_id) != creation_plan_id:
        raise CreativeContextResolutionError("creation_plan_context_mismatch")
    plan_project_id = _value(creation_plan, "project_id")
    if plan_project_id is not None and str(plan_project_id) != project_id:
        raise CreativeContextResolutionError("creation_plan_project_mismatch")
    status = str(_value(creation_plan, "status", "")).lower()
    if status in {"cancelled", "invalidated"}:
        raise CreativeContextResolutionError("creation_plan_unavailable", details={"status": status})
    if not _plan_previewed(creation_plan, previewed):
        raise CreativeContextResolutionError("creation_plan_preview_required")
    if requested_generation_mode is not None:
        raise CreativeContextResolutionError("generation_mode_override_forbidden")

    snapshot = _plan_snapshot(creation_plan)
    if snapshot is not None:
        if _value(snapshot, "project_id") is not None and str(_value(snapshot, "project_id")) != project_id:
            raise CreativeContextResolutionError("creation_plan_project_mismatch")
        for field in ("content_mode", "generation_mode", "grid_storyboard", "aspect_ratio", "style", "model_config"):
            expected = _value(snapshot, field)
            if expected is None:
                continue
            actual = project.get(field)
            if field == "model_config" and actual is None:
                actual = project.get("model_config_snapshot")
            if actual != expected:
                code = "generation_mode_changed" if field == "generation_mode" else "project_snapshot_changed"
                raise CreativeContextResolutionError(code, details={"field": field})

    plan_skill_id = _plan_skill_id(creation_plan)
    if current_skill_id and plan_skill_id and current_skill_id != plan_skill_id:
        raise CreativeContextResolutionError(
            "creation_plan_skill_mismatch",
            details={"creation_plan_skill_id": plan_skill_id, "current_skill_id": current_skill_id},
        )
    effective_skill_id = current_skill_id or plan_skill_id
    if effective_skill_id is None:
        raise CreativeContextResolutionError("creation_plan_skill_required")
    skill = _skill_by_id(effective_skill_id)
    available_inputs = {_RESOURCE_INPUTS[item["resource_type"]] for item in selected}
    report = compatibility_report(skill, project, available_inputs)
    persisted_report = _mapping(_value(creation_plan, "compatibility_report"))
    if persisted_report is not None and persisted_report.get("compatible") is False:
        report = dict(persisted_report)
    if not report.get("compatible"):
        raise CreativeContextResolutionError("creation_skill_incompatible", details=report)
    planned_ids = _plan_resource_ids(creation_plan)
    selected_ids = {item["id"] for item in selected}
    if planned_ids and planned_ids != selected_ids:
        raise CreativeContextResolutionError("creation_plan_resources_mismatch")

    parameters = _mapping(_value(creation_plan, "parameters", _value(creation_plan, "parameters_json"))) or {}
    forbidden = {"generation_mode_override", "content_mode_override", "grid_storyboard_override"}
    if forbidden.intersection(parameters) or any(str(key).endswith("_override") for key in parameters):
        raise CreativeContextResolutionError("gate_bypass_forbidden")

    raw_cost = _value(creation_plan, "estimated_cost", 0)
    estimated_cost = float(raw_cost) if isinstance(raw_cost, (int, float, str)) else 0.0
    requires_confirmation = bool(_value(creation_plan, "requires_confirmation", False)) or estimated_cost > 0
    plan_confirmed = bool(_value(creation_plan, "confirmed", False)) or status == "confirmed"
    if requires_confirmation and not confirmed and not plan_confirmed:
        raise CreativeContextResolutionError("confirmation_required", details={"estimated_cost": estimated_cost})

    quality_value = _value(creation_plan, "quality_gate", _value(creation_plan, "quality_gate_status"))
    quality_result, quality_required = _gate(quality_value)
    if quality_gate_passed is not None:
        quality_result = quality_gate_passed
    if quality_result is False:
        raise CreativeContextResolutionError("quality_gate_failed")
    if quality_required and quality_result is not True:
        raise CreativeContextResolutionError("quality_gate_required")

    review_points = _decoded(_value(creation_plan, "review_points", ()))
    approval_value = _value(creation_plan, "approval", _value(creation_plan, "approval_status"))
    approval_result, approval_required = _gate(approval_value)
    if _sequence(review_points):
        approval_required = True
    if approval_status is not None:
        approval_result = approval_status.lower() in _APPROVED_STATUSES
    if approval_required and approval_result is not True:
        raise CreativeContextResolutionError("approval_required")

    run_info: dict[str, object] = {}
    if workflow_run_id:
        if workflow_run is None:
            raise CreativeContextResolutionError("workflow_run_details_required")
        run_id = _value(workflow_run, "id", _value(workflow_run, "workflow_run_id"))
        if run_id is not None and str(run_id) != workflow_run_id:
            raise CreativeContextResolutionError("workflow_run_context_mismatch")
        if _value(workflow_run, "project_id") is not None and str(_value(workflow_run, "project_id")) != project_id:
            raise CreativeContextResolutionError("workflow_run_project_mismatch")
        if _value(workflow_run, "error_code") == "quality_gate_failed":
            raise CreativeContextResolutionError("quality_gate_failed")
        if str(_value(workflow_run, "status", "")).lower() == "waiting_review" and approval_result is not True:
            raise CreativeContextResolutionError("approval_required")
        run_mode = _value(workflow_run, "generation_mode")
        if run_mode is not None and run_mode != project.get("generation_mode"):
            raise CreativeContextResolutionError("generation_mode_changed")
        run_info = {"id": workflow_run_id, "status": _value(workflow_run, "status")}

    return effective_skill_id, {
        "previewed": True,
        "confirmed": bool(confirmed or plan_confirmed or not requires_confirmation),
        "quality_gate_passed": quality_result,
        "approval_status": approval_status or ("approved" if approval_result is True else "not_required"),
        "requires_confirmation": requires_confirmation,
        "workflow_run": run_info,
    }


def _normalize_reference(value: object) -> str:
    if not isinstance(value, str):
        return " ".join(str(value).casefold().strip().split()) if value is not None else ""
    return " ".join(value.casefold().strip().split())


def _canonical_resource_type(resource_type: object, *, item_type: object = None, media_kind: object = None) -> str:
    value = str(resource_type or "").casefold().strip()
    item = str(item_type or "").casefold().strip()
    kind = str(media_kind or "").casefold().strip()
    if value in {"character", "characters"} or item in {"character", "characters"}:
        return "character"
    if value in {"scene", "scenes"} or item in {"scene", "scenes"}:
        return "scene"
    if value in {"prop", "props"} or item in {"prop", "props"}:
        return "prop"
    if value in {"shot", "shots"} or item in {"shot", "shots"}:
        return "shot"
    if value in {"video", "media_video"} or kind == "video":
        return "video"
    if value in {"audio", "media_audio"} or kind == "audio":
        return "audio"
    if value in {"image", "media_image"} or kind == "image":
        return "image"
    if value == "media_asset":
        return "media_asset"
    return value


def _candidate(
    resource_id: object,
    resource_type: str,
    *,
    labels: Sequence[object] = (),
    episode_id: object = None,
    gender: object = None,
) -> dict[str, object] | None:
    if resource_id is None or not str(resource_id).strip():
        return None
    normalized_labels = {_normalize_reference(label) for label in labels if _normalize_reference(label)}
    return {
        "id": str(resource_id),
        "resource_type": resource_type,
        "labels": normalized_labels,
        "episode_id": str(episode_id) if episode_id is not None else None,
        "gender": _normalize_reference(gender),
    }


def _named_entity_candidates(project: Mapping[str, object], field: str) -> list[dict[str, object]]:
    entities = _project_entities(project, field)
    if entities is None:
        return []
    values = entities.items() if isinstance(entities, Mapping) else ((None, item) for item in _sequence(entities))
    result: list[dict[str, object]] = []
    for key, entity in values:
        identifier = _value(entity, "id") or _value(entity, f"{field}_id") or key
        labels = [key, _value(entity, "name"), _value(entity, "label"), _value(entity, "title")]
        aliases = _value(entity, "aliases", ())
        if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
            labels.extend(aliases)
        item = _candidate(identifier, field, labels=labels, gender=_value(entity, "gender"))
        if item is not None:
            result.append(item)
    return result


def _shot_candidates(project: Mapping[str, object]) -> list[dict[str, object]]:
    episodes = _project_entities(project, "episode")
    result: list[dict[str, object]] = []
    if episodes is not None:
        episode_values = (
            episodes.items() if isinstance(episodes, Mapping) else ((None, item) for item in _sequence(episodes))
        )
        for episode_key, episode in episode_values:
            episode_id = _value(episode, "id") or _value(episode, "episode_id") or episode_key
            shots = _value(episode, "shots", _value(episode, "shot", ()))
            shot_values = shots.items() if isinstance(shots, Mapping) else ((None, item) for item in _sequence(shots))
            for shot_key, shot in shot_values:
                identifier = _value(shot, "id") or _value(shot, "shot_id") or shot_key
                item = _candidate(
                    identifier,
                    "shot",
                    labels=[shot_key, _value(shot, "name"), _value(shot, "label"), _value(shot, "title")],
                    episode_id=episode_id,
                )
                if item is not None:
                    result.append(item)
    top_level = _project_entities(project, "shot")
    if top_level is not None:
        values = (
            top_level.items() if isinstance(top_level, Mapping) else ((None, item) for item in _sequence(top_level))
        )
        for key, shot in values:
            identifier = _value(shot, "id") or _value(shot, "shot_id") or key
            item = _candidate(
                identifier,
                "shot",
                labels=[key, _value(shot, "name"), _value(shot, "label"), _value(shot, "title")],
                episode_id=_value(shot, "episode_id"),
            )
            if item is not None and not any(item["id"] == existing["id"] for existing in result):
                result.append(item)
    return result


def _board_candidates(board_items: Sequence[object], media_assets: object) -> list[dict[str, object]]:
    if isinstance(media_assets, Mapping):
        assets_by_id = {str(key): value for key, value in media_assets.items()}
    else:
        assets_by_id = {
            str(_value(asset, "id")): asset for asset in _sequence(media_assets) if _value(asset, "id") is not None
        }
    result: list[dict[str, object]] = []
    for item in board_items:
        metadata = _mapping(_value(item, "display_settings_json", _value(item, "display_settings"))) or {}
        resource_id = _value(item, "resource_id") or _value(item, "id")
        asset = assets_by_id.get(str(resource_id))
        resource_type = _canonical_resource_type(
            _value(item, "resource_type"),
            item_type=_value(item, "item_type"),
            media_kind=_value(asset, "kind", _value(asset, "media_kind"))
            if asset is not None
            else metadata.get("kind"),
        )
        candidate = _candidate(
            resource_id,
            resource_type,
            labels=[
                _value(item, "name"),
                _value(item, "label"),
                _value(item, "title"),
                metadata.get("name"),
                metadata.get("label"),
                metadata.get("title"),
            ],
            episode_id=_value(item, "episode_id") or metadata.get("episode_id"),
            gender=metadata.get("gender"),
        )
        if candidate is not None:
            result.append(candidate)
    return result


def _selected_candidates(
    selected_resources: Sequence[SelectedResource], media_assets: object
) -> list[dict[str, object]]:
    if isinstance(media_assets, Mapping):
        assets_by_id = {str(key): value for key, value in media_assets.items()}
    else:
        assets_by_id = {
            str(_value(asset, "id")): asset for asset in _sequence(media_assets) if _value(asset, "id") is not None
        }
    result: list[dict[str, object]] = []
    for resource in selected_resources:  # pyright: ignore[reportGeneralTypeIssues]
        asset = assets_by_id.get(resource.id)
        item = _candidate(
            resource.id,
            _canonical_resource_type(
                resource.resource_type,
                media_kind=_value(asset, "kind", _value(asset, "media_kind")) if asset is not None else None,
            ),
        )
        if item is not None:
            result.append(item)
    return result


def _unique_candidates(candidates: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str], dict[str, object]] = {}
    for candidate in candidates:
        key = (str(candidate["id"]), str(candidate["resource_type"]))
        existing = unique.get(key)
        if existing is None:
            unique[key] = dict(candidate)
            continue
        labels = _candidate_labels(existing)
        labels.update(_candidate_labels(candidate))
        existing["labels"] = labels
        if existing.get("episode_id") is None:
            existing["episode_id"] = candidate.get("episode_id")
        if not existing.get("gender"):
            existing["gender"] = candidate.get("gender")
    return list(unique.values())


def _candidate_labels(item: Mapping[str, object]) -> set[str]:
    labels = item.get("labels")
    if not isinstance(labels, (list, tuple, set, frozenset)):
        return set()
    return {label for label in labels if isinstance(label, str)}


def _reference_candidates(
    reference: ContextReference,
    *,
    project: Mapping[str, object],
    selected_resources: Sequence[SelectedResource],
    board_items: Sequence[object],
    media_assets: object,
) -> list[dict[str, object]]:
    selected = _selected_candidates(selected_resources, media_assets)
    board = _board_candidates(board_items, media_assets)
    expected = _canonical_resource_type(reference.expected_type)
    text = _normalize_reference(reference.text)
    if text in {"当前镜头", "current shot", "this shot"}:
        return _unique_candidates([item for item in selected + board if item["resource_type"] == "shot"])
    if text in {"这个视频", "当前视频", "this video", "current video"}:
        return _unique_candidates([item for item in selected + board if item["resource_type"] == "video"])
    if text in {"她", "他", "她的", "his", "her", "the character"}:
        candidates = _unique_candidates(
            [item for item in selected + board if item["resource_type"] == "character"]
            or _named_entity_candidates(project, "character")
        )
        if text in {"她", "她的", "her"}:
            female = [item for item in candidates if item.get("gender") in {"female", "女", "woman"}]
            if female:
                candidates = female
        return candidates
    candidates = _named_entity_candidates(project, "character") if not expected or expected == "character" else []
    candidates += selected + board
    candidates = _unique_candidates(candidates)
    return [
        item
        for item in candidates
        if text in _candidate_labels(item) and (not expected or item["resource_type"] == expected)
    ]


def resolve_context_references(
    *,
    project_id: str,
    project: Mapping[str, object],
    references: Sequence[ContextReference] = (),
    context_references: Sequence[ContextReference] | None = None,
    selected_resources: Sequence[SelectedResource] = (),
    board_items: Sequence[object] = (),
    media_assets: object = None,
    episode_id: str | None = None,
    shot_id: str | None = None,
) -> dict[str, object]:
    """Resolve references to stable IDs without creating or mutating anything."""

    if context_references is not None:
        references = context_references

    if not project_id.strip():
        raise CreativeContextResolutionError("project_id_required")
    _validate_project_id(project_id, project)
    _validate_project_id(project_id, project)
    resolved_resources = list(selected_resources)
    resolved_episode_id = episode_id.strip() if episode_id else None
    resolved_shot_id = shot_id.strip() if shot_id else None
    shot_catalog = _shot_candidates(project)
    resolutions: list[dict[str, object]] = []
    for reference in references:
        if not reference.text.strip():
            raise CreativeContextResolutionError("context_reference_required")
        text = _normalize_reference(reference.text)
        if text in {"当前镜头", "current shot", "this shot"} and resolved_shot_id:
            candidates = [item for item in shot_catalog if item["id"] == resolved_shot_id]
        else:
            candidates = _reference_candidates(
                reference,
                project=project,
                selected_resources=tuple(resolved_resources),
                board_items=board_items,
                media_assets=media_assets,
            )
        if not candidates:
            raise CreativeContextResolutionError(
                "context_reference_unresolved",
                details={"reference": reference.text, "expected_type": reference.expected_type},
            )
        if len(candidates) > 1:
            raise CreativeContextResolutionError(
                "ambiguous_context_reference",
                details={
                    "reference": reference.text,
                    "expected_type": reference.expected_type,
                    "candidates": [{"id": item["id"], "resource_type": item["resource_type"]} for item in candidates],
                },
            )
        match = candidates[0]
        matched_id = str(match["id"])
        matched_type = str(match["resource_type"])
        if matched_type == "shot":
            candidate_episode_id = match.get("episode_id")
            if resolved_shot_id is not None and resolved_shot_id != matched_id:
                raise CreativeContextResolutionError(
                    "context_reference_conflict", details={"reference": reference.text}
                )
            if (
                resolved_episode_id is not None
                and candidate_episode_id is not None
                and resolved_episode_id != candidate_episode_id
            ):
                raise CreativeContextResolutionError(
                    "context_reference_conflict", details={"reference": reference.text}
                )
            resolved_shot_id = matched_id
            if resolved_episode_id is None and candidate_episode_id is not None:
                resolved_episode_id = str(candidate_episode_id)
            if resolved_episode_id is None:
                episode_matches = {
                    str(item["episode_id"])
                    for item in shot_catalog
                    if item["id"] == matched_id and item.get("episode_id") is not None
                }
                if len(episode_matches) == 1:
                    resolved_episode_id = next(iter(episode_matches))
        if not any(
            resource.id == matched_id and _canonical_resource_type(resource.resource_type) == matched_type
            for resource in resolved_resources
        ):
            resolved_resources.append(SelectedResource(matched_id, matched_type))
        resolutions.append({"reference": reference.text, "id": matched_id, "resource_type": matched_type})
    return {
        "project_id": project_id,
        "episode_id": resolved_episode_id,
        "shot_id": resolved_shot_id,
        "selected_resources": [{"id": item.id, "resource_type": item.resource_type} for item in resolved_resources],
        "selected_media_asset_ids": [
            item.id
            for item in resolved_resources
            if _canonical_resource_type(item.resource_type) in {"image", "video", "audio", "media_asset"}
        ],
        "references": resolutions,
        "disambiguated": True,
    }


def resolve_creation_context(
    *,
    project_id: str,
    project: Mapping[str, object],
    selected_resources: Sequence[SelectedResource],
    creative_board_id: str | None = None,
    episode_id: str | None = None,
    shot_id: str | None = None,
    current_skill_id: str | None = None,
    creation_plan_id: str | None = None,
    workflow_run_id: str | None = None,
    board: Mapping[str, object] | None = None,
    board_items: Sequence[object] = (),
    media_assets: object = None,
    creation_plan: object = None,
    workflow_run: object = None,
    previewed: bool | None = None,
    confirmed: bool = False,
    quality_gate_passed: bool | None = None,
    approval_status: str | None = None,
    allow_gate_bypass: bool = False,
    generation_mode: str | None = None,
    generation_mode_override: str | None = None,
    context_references: Sequence[ContextReference] = (),
) -> dict[str, object]:
    """Resolve context without creating or mutating a Creation Plan or run."""

    if not project_id.strip():
        return {"status": "error", "error": {"code": "missing_project_id"}, "resolved": {}}
    _validate_project_id(project_id, project)
    reference_resolution: dict[str, object] = {}
    if context_references:
        reference_resolution = resolve_context_references(
            project_id=project_id,
            project=project,
            references=context_references,
            selected_resources=selected_resources,
            board_items=board_items,
            media_assets=media_assets,
            episode_id=episode_id,
            shot_id=shot_id,
        )
        resolved_episode_id = reference_resolution.get("episode_id")
        if isinstance(resolved_episode_id, str):
            episode_id = resolved_episode_id
        resolved_shot_id = reference_resolution.get("shot_id")
        if isinstance(resolved_shot_id, str):
            shot_id = resolved_shot_id
        resolved_resources = reference_resolution.get("selected_resources", ())
        if isinstance(resolved_resources, Sequence) and not isinstance(resolved_resources, (str, bytes)):
            selected_resources = tuple(
                SelectedResource(str(item["id"]), str(item["resource_type"]))
                for item in resolved_resources
                if isinstance(item, Mapping) and "id" in item and "resource_type" in item
            )
    if workflow_run_id and not creation_plan_id:
        raise CreativeContextResolutionError(
            "workflow_run_requires_creation_plan", details={"workflow_run_id": workflow_run_id}
        )
    if not selected_resources:
        raise CreativeContextResolutionError("resource_selection_required")

    seen_ids: set[str] = set()
    normalized: list[dict[str, str]] = []
    available_inputs: set[str] = set()
    for resource in selected_resources:  # pyright: ignore[reportGeneralTypeIssues]
        resource_id = resource.id.strip()
        resource_type = resource.resource_type.strip().lower()
        if not resource_id:
            raise CreativeContextResolutionError("resource_id_required")
        if resource_id in seen_ids:
            raise CreativeContextResolutionError("ambiguous_duplicate_resource", details={"resource_id": resource_id})
        if resource_type not in _RESOURCE_INPUTS:
            raise CreativeContextResolutionError("unknown_resource_type", details={"resource_type": resource_type})
        seen_ids.add(resource_id)
        available_inputs.add(_RESOURCE_INPUTS[resource_type])
        normalized.append({"id": resource_id, "resource_type": resource_type})

    _validate_episode_and_shot(
        project, episode_id.strip() if episode_id else None, shot_id.strip() if shot_id else None
    )
    _validate_board(project_id, creative_board_id, board, normalized, board_items)
    if not creation_plan_id:
        raise CreativeContextResolutionError("creation_plan_required")
    _validate_media_assets(project, normalized, media_assets)
    available = [
        {
            "id": skill.id,
            "version_id": skill.latest_version.id,
            "title": skill.latest_version.title,
            "summary": skill.latest_version.summary,
        }
        for skill, reason in list_official_creation_skills(project, available_inputs)
        if reason is None
    ]
    requested_mode = generation_mode_override if generation_mode_override is not None else generation_mode
    effective_skill_id, gates = _validate_plan_and_gates(
        project_id=project_id,
        project=project,
        selected=normalized,
        current_skill_id=current_skill_id,
        creation_plan_id=creation_plan_id,
        creation_plan=creation_plan,
        workflow_run_id=workflow_run_id,
        workflow_run=workflow_run,
        previewed=previewed,
        confirmed=confirmed,
        quality_gate_passed=quality_gate_passed,
        approval_status=approval_status,
        allow_gate_bypass=allow_gate_bypass,
        requested_generation_mode=requested_mode,
    )
    return {
        "project_id": project_id,
        "creative_board_id": creative_board_id,
        "episode_id": episode_id,
        "shot_id": shot_id,
        "selected_resources": normalized,
        "selected_media_asset_ids": [
            item["id"] for item in normalized if item["resource_type"] in _MEDIA_RESOURCE_TYPES
        ],
        "current_skill_id": effective_skill_id,
        "creation_plan_id": creation_plan_id,
        "workflow_run_id": workflow_run_id,
        "available_skills": available,
        "disambiguated": True,
        "generation_mode": project.get("generation_mode"),
        "gates": gates,
        "requires_creation_plan_preview": True,
        "requires_confirmation_for_high_cost_operations": True,
        "context_reference_resolutions": reference_resolution.get("references", []),
    }
