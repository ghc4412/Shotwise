"""Immutable domain model for a single creative execution plan.

The Project owns content_mode, generation_mode, and grid_storyboard. A
CreationPlan may capture those values, but it cannot supply replacements for
them. This module is independent from persistence and web frameworks so the
ownership rule is enforced at the domain seam.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from lib.workflow import CONTENT_MODES, GENERATION_MODES


class CreationPlanError(ValueError):
    """Raised when a Project context cannot produce a valid CreationPlan."""


class _FrozenMapping(tuple[tuple[str, object], ...]):
    """Tuple-backed mapping marker used to keep nested inputs immutable."""


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise CreationPlanError("skill inputs must use string keys")
            items.append((key, _freeze(item)))
        return _FrozenMapping(sorted(items))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    raise CreationPlanError(f"skill inputs contain unsupported value: {type(value).__name__}")


def _thaw(value: object) -> object:
    if isinstance(value, _FrozenMapping):
        return {key: _thaw(item) for key, item in value}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _non_empty(value: str, field_name: str) -> str:
    if not value.strip():
        raise CreationPlanError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ProjectContextSnapshot:
    """Read-only values captured from the Project that owns generation rules."""

    project_id: str
    content_mode: str
    generation_mode: str
    grid_storyboard: bool
    aspect_ratio: str = ""
    style: str = ""
    model_config: _FrozenMapping = _FrozenMapping()

    def __post_init__(self) -> None:
        _non_empty(self.project_id, "project_id")
        if self.content_mode not in CONTENT_MODES:
            raise CreationPlanError(f"unsupported content_mode: {self.content_mode}")
        if self.generation_mode not in GENERATION_MODES:
            raise CreationPlanError(f"unsupported generation_mode: {self.generation_mode}")
        if not isinstance(self.aspect_ratio, str):
            raise CreationPlanError("Project aspect_ratio must be a string")
        if not isinstance(self.style, str):
            raise CreationPlanError("Project style must be a string")
        if not isinstance(self.model_config, _FrozenMapping):
            raise CreationPlanError("Project model_config must be a mapping")

    @classmethod
    def from_project(cls, project_id: str, project: Mapping[str, object]) -> ProjectContextSnapshot:
        """Capture owned Project fields without accepting Plan overrides."""

        content_mode = project.get("content_mode", "drama")
        generation_mode = project.get("generation_mode")
        grid_storyboard = project.get("grid_storyboard", False)
        aspect_ratio = project.get("aspect_ratio", "")
        style = project.get("style", "")
        model_config = project.get("model_settings", project.get("model_config", {}))
        if not isinstance(content_mode, str):
            raise CreationPlanError("Project content_mode must be a string")
        if not isinstance(generation_mode, str):
            raise CreationPlanError("Project generation_mode must be a string")
        if not isinstance(grid_storyboard, bool):
            raise CreationPlanError("Project grid_storyboard must be a boolean")
        if not isinstance(aspect_ratio, str):
            raise CreationPlanError("Project aspect_ratio must be a string")
        if not isinstance(style, str):
            raise CreationPlanError("Project style must be a string")
        frozen_model_config = _freeze(model_config)
        if not isinstance(frozen_model_config, _FrozenMapping):
            raise CreationPlanError("Project model_config must be a mapping")
        return cls(
            project_id=project_id,
            content_mode=content_mode,
            generation_mode=generation_mode,
            grid_storyboard=grid_storyboard,
            aspect_ratio=aspect_ratio,
            style=style,
            model_config=frozen_model_config,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "content_mode": self.content_mode,
            "generation_mode": self.generation_mode,
            "grid_storyboard": self.grid_storyboard,
            "aspect_ratio": self.aspect_ratio,
            "style": self.style,
            "model_config": _thaw(self.model_config),
        }


@dataclass(frozen=True, slots=True)
class CompatibilityCheck:
    """The compatibility result recorded when a CreationPlan is compiled."""

    compatible: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unique_reasons = tuple(dict.fromkeys(self.reasons))
        if unique_reasons != self.reasons:
            raise CreationPlanError("compatibility reasons must be unique and ordered")
        if self.compatible and self.reasons:
            raise CreationPlanError("a compatible plan cannot contain incompatibility reasons")
        if not self.compatible and not self.reasons:
            raise CreationPlanError("an incompatible plan must record at least one reason")


@dataclass(frozen=True, slots=True)
class CreationPlan:
    """An immutable, deterministic execution plan for one selected Skill."""

    plan_id: str
    skill_id: str
    workflow_revision: str
    project_context: ProjectContextSnapshot
    skill_inputs: _FrozenMapping
    compatibility: CompatibilityCheck
    fingerprint: str
    skill_maintainer: Literal["official"] = "official"

    def __post_init__(self) -> None:
        _non_empty(self.plan_id, "plan_id")
        _non_empty(self.skill_id, "skill_id")
        _non_empty(self.workflow_revision, "workflow_revision")
        if self.skill_maintainer != "official":
            raise CreationPlanError("only officially maintained creation Skills are supported")
        expected = _fingerprint(
            self.skill_id,
            self.workflow_revision,
            self.project_context,
            self.skill_inputs,
            self.compatibility,
        )
        if self.fingerprint != expected:
            raise CreationPlanError("CreationPlan fingerprint does not match its immutable contents")

    @classmethod
    def compile(
        cls,
        *,
        plan_id: str,
        skill_id: str,
        workflow_revision: str,
        project_context: ProjectContextSnapshot,
        skill_inputs: Mapping[str, object],
        supported_content_modes: Iterable[str] | None = None,
        supported_generation_modes: Iterable[str] | None = None,
    ) -> CreationPlan:
        """Compile a plan from a Project snapshot and Skill-owned inputs.

        generation_mode intentionally is not a parameter. Callers must obtain
        it from the ProjectContextSnapshot, making a second source of truth
        impossible through this interface.
        """

        frozen_inputs = _freeze(skill_inputs)
        if not isinstance(frozen_inputs, _FrozenMapping):
            raise CreationPlanError("skill_inputs must be a mapping")
        forbidden = {"generation_mode_override", "content_mode_override", "grid_storyboard_override"}
        received_forbidden = sorted(forbidden.intersection(skill_inputs))
        if received_forbidden:
            raise CreationPlanError(f"CreationPlan does not accept mode overrides: {', '.join(received_forbidden)}")
        reasons: list[str] = []
        if supported_content_modes is not None and project_context.content_mode not in set(supported_content_modes):
            reasons.append("content_mode_not_supported")
        if supported_generation_modes is not None and project_context.generation_mode not in set(
            supported_generation_modes
        ):
            reasons.append("generation_mode_not_supported")
        compatibility = CompatibilityCheck(compatible=not reasons, reasons=tuple(reasons))
        fingerprint = _fingerprint(
            skill_id,
            workflow_revision,
            project_context,
            frozen_inputs,
            compatibility,
        )
        return cls(
            plan_id=plan_id,
            skill_id=skill_id,
            workflow_revision=workflow_revision,
            project_context=project_context,
            skill_inputs=frozen_inputs,
            compatibility=compatibility,
            fingerprint=fingerprint,
        )

    @property
    def is_compatible(self) -> bool:
        return self.compatibility.compatible

    def require_compatible(self) -> None:
        if not self.is_compatible:
            reasons = ", ".join(self.compatibility.reasons)
            raise CreationPlanError(f"CreationPlan is incompatible: {reasons}")

    def assert_project_matches(self, project: Mapping[str, object]) -> None:
        """Reject starting a plan after any owned Project setting changed."""

        current = ProjectContextSnapshot.from_project(self.project_context.project_id, project)
        if current != self.project_context:
            raise CreationPlanError("Project changed after CreationPlan preview; compile a new plan")

    def to_dict(self) -> dict[str, object]:
        """Return a serialization view; the source Project remains untouched."""

        return {
            "plan_id": self.plan_id,
            "skill_id": self.skill_id,
            "workflow_revision": self.workflow_revision,
            "project_context": {
                **self.project_context.to_dict(),
            },
            "skill_inputs": _thaw(self.skill_inputs),
            "compatibility": {
                "compatible": self.compatibility.compatible,
                "reasons": list(self.compatibility.reasons),
            },
            "fingerprint": self.fingerprint,
            "skill_maintainer": self.skill_maintainer,
        }


def _fingerprint(
    skill_id: str,
    workflow_revision: str,
    project_context: ProjectContextSnapshot,
    skill_inputs: _FrozenMapping,
    compatibility: CompatibilityCheck,
) -> str:
    payload = {
        "skill_id": skill_id,
        "workflow_revision": workflow_revision,
        "project_context": {
            "project_id": project_context.project_id,
            "content_mode": project_context.content_mode,
            "generation_mode": project_context.generation_mode,
            "grid_storyboard": project_context.grid_storyboard,
            "aspect_ratio": project_context.aspect_ratio,
            "style": project_context.style,
            "model_config": _thaw(project_context.model_config),
        },
        "skill_inputs": _thaw(skill_inputs),
        "compatibility": {
            "compatible": compatibility.compatible,
            "reasons": list(compatibility.reasons),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
