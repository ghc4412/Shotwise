"""Database-backed official Creation Skill catalog and manifest synchronizer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.creation_skills import OFFICIAL_CREATION_SKILLS, CreationSkillDefinition, CreationSkillVersion
from lib.db.base import utc_now
from lib.db.models.creation_skill import (
    CreationSkillCompatibilityRecord,
    CreationSkillDefinitionRecord,
    CreationSkillVersionRecord,
)
from lib.db.models.workflow import WorkflowRevision
from server.services import workflows as workflow_service


class CreationSkillManifestConflict(RuntimeError):
    """The manifest attempted to mutate an already frozen release."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _manifest_payload(skill: CreationSkillDefinition) -> dict[str, object]:
    version = skill.latest_version
    compatibility = version.compatibility
    return {
        "version_id": version.id,
        "version": version.version,
        "title": version.title,
        "summary": version.summary,
        "category": version.category,
        "workflow_template_revision_alias": version.workflow_template_revision_alias,
        "expected_outputs": list(version.expected_outputs),
        "review_required": version.review_required,
        "estimated_cost_hint": version.estimated_cost_hint,
        "content_modes": sorted(compatibility.content_modes),
        "generation_modes": sorted(compatibility.generation_modes),
        "required_inputs": sorted(compatibility.required_inputs),
        "scopes": sorted(compatibility.scopes),
        "grid_storyboards": sorted(compatibility.grid_storyboards)
        if compatibility.grid_storyboards is not None
        else None,
    }


def _stored_payload(
    version: CreationSkillVersionRecord, compatibility: CreationSkillCompatibilityRecord
) -> dict[str, object]:
    return {
        "version_id": version.id,
        "version": version.version,
        "title": version.title,
        "summary": version.summary,
        "category": version.category,
        "workflow_template_revision_alias": version.workflow_template_revision_alias,
        "expected_outputs": _decode(version.expected_outputs_json, []),
        "review_required": version.review_required,
        "estimated_cost_hint": version.estimated_cost_hint,
        "content_modes": _decode(compatibility.content_modes_json, []),
        "generation_modes": _decode(compatibility.generation_modes_json, []),
        "required_inputs": _decode(compatibility.required_inputs_json, []),
        "scopes": _decode(compatibility.scopes_json, []),
        "grid_storyboards": _decode(compatibility.grid_storyboards_json, None),
    }


def _version_from_records(
    definition: CreationSkillDefinitionRecord,
    version: CreationSkillVersionRecord,
    compatibility: CreationSkillCompatibilityRecord,
) -> CreationSkillDefinition:
    from lib.creation_skills import CreationSkillCompatibility

    skill_version = CreationSkillVersion(
        id=version.id,
        skill_id=version.skill_id,
        version=version.version,
        title=version.title,
        summary=version.summary,
        category=version.category,
        workflow_template_revision_alias=version.workflow_template_revision_alias,
        compatibility=CreationSkillCompatibility(
            content_modes=frozenset(_decode(compatibility.content_modes_json, [])),
            generation_modes=frozenset(_decode(compatibility.generation_modes_json, [])),
            required_inputs=frozenset(_decode(compatibility.required_inputs_json, [])),
            scopes=frozenset(_decode(compatibility.scopes_json, ["project"])),
            grid_storyboards=(
                frozenset(_decode(compatibility.grid_storyboards_json, []))
                if compatibility.grid_storyboards_json is not None
                else None
            ),
        ),
        expected_outputs=tuple(_decode(version.expected_outputs_json, [])),
        review_required=version.review_required,
        estimated_cost_hint=version.estimated_cost_hint,
        workflow_revision_id=version.workflow_revision_id,
    )
    return CreationSkillDefinition(
        id=definition.id,
        slug=definition.slug,
        latest_version=skill_version,
        official=True,
        active=definition.active,
    )


async def get_persisted_creation_skill_version(
    session: AsyncSession, skill_version_id: str
) -> tuple[CreationSkillDefinition, CreationSkillVersion] | None:
    """Resolve an active, published release for plan compilation."""

    row = (
        await session.execute(
            select(CreationSkillDefinitionRecord, CreationSkillVersionRecord, CreationSkillCompatibilityRecord)
            .join(CreationSkillVersionRecord, CreationSkillVersionRecord.skill_id == CreationSkillDefinitionRecord.id)
            .join(
                CreationSkillCompatibilityRecord,
                CreationSkillCompatibilityRecord.skill_version_id == CreationSkillVersionRecord.id,
            )
            .join(WorkflowRevision, WorkflowRevision.id == CreationSkillVersionRecord.workflow_revision_id)
            .where(
                CreationSkillVersionRecord.id == skill_version_id,
                CreationSkillDefinitionRecord.active.is_(True),
                CreationSkillVersionRecord.status == "published",
                WorkflowRevision.status == "published",
            )
        )
    ).one_or_none()
    if row is None:
        return None
    definition, version, compatibility = row
    skill = _version_from_records(definition, version, compatibility)
    return skill, skill.latest_version


async def _ensure_official_workflow_revision(
    session: AsyncSession,
    skill: CreationSkillDefinition,
    *,
    current_revision_id: str | None,
) -> str:
    """Resolve or publish the immutable Workflow Revision used by an official Skill release."""

    if current_revision_id and not current_revision_id.startswith("official:"):
        revision = await session.get(WorkflowRevision, current_revision_id)
        if revision is None:
            raise CreationSkillManifestConflict(
                f"Creation Skill {skill.id} is bound to missing Workflow Revision {current_revision_id}"
            )
        if revision.status != "published":
            raise CreationSkillManifestConflict(
                f"Creation Skill {skill.id} is bound to unpublished Workflow Revision {current_revision_id}"
            )
        return current_revision_id

    content_mode = next(iter(skill.latest_version.compatibility.content_modes), "drama")
    generation_mode = next(iter(skill.latest_version.compatibility.generation_modes), "storyboard")
    nodes, edges = workflow_service.legacy_linear_graph()
    definition = await workflow_service.create_definition(
        session,
        workspace_id="official",
        project_id="__official_creation_skills__",
        name=f"Official Creation Skill: {skill.id} v{skill.latest_version.version}",
        actor_id="system",
    )
    revision = await workflow_service.create_revision(
        session,
        definition_id=str(definition["id"]),
        actor_id="system",
        content_mode=content_mode,
        generation_mode=generation_mode,
        input_schema={
            "type": "object",
            "required": sorted(skill.latest_version.compatibility.required_inputs),
            "properties": {},
            "additionalProperties": True,
        },
        template_lock={
            "kind": "official_creation_skill",
            "skill_id": skill.id,
            "skill_version_id": skill.latest_version.id,
            "workflow_template_revision_alias": skill.latest_version.workflow_template_revision_alias,
        },
        nodes=nodes,
        edges=edges,
    )
    revision_id = str(revision["id"])
    await workflow_service.publish_revision(session, revision_id, actor_id="system")
    return revision_id


async def sync_official_creation_skills(session: AsyncSession) -> int:
    """Publish missing manifest releases without mutating frozen releases."""

    manifest_by_id = {skill.id: skill for skill in OFFICIAL_CREATION_SKILLS}
    changed = 0
    existing = (
        (
            await session.execute(
                select(CreationSkillDefinitionRecord).where(CreationSkillDefinitionRecord.official.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for record in existing:
        if record.id not in manifest_by_id and record.active:
            record.active = False
            changed += 1

    for skill in OFFICIAL_CREATION_SKILLS:
        definition = await session.get(CreationSkillDefinitionRecord, skill.id)
        if definition is None:
            definition = CreationSkillDefinitionRecord(
                id=skill.id,
                slug=skill.slug,
                official=True,
                active=skill.active,
            )
            session.add(definition)
            changed += 1
        elif definition.slug != skill.slug or definition.official is not True:
            raise CreationSkillManifestConflict(f"Creation Skill definition {skill.id} conflicts with the manifest")

        version = await session.get(CreationSkillVersionRecord, skill.latest_version.id)
        if version is None:
            compatibility = skill.latest_version.compatibility
            workflow_revision_id = await _ensure_official_workflow_revision(
                session,
                skill,
                current_revision_id=skill.latest_version.workflow_revision_id,
            )
            session.add(
                CreationSkillVersionRecord(
                    id=skill.latest_version.id,
                    skill_id=skill.id,
                    version=skill.latest_version.version,
                    title=skill.latest_version.title,
                    summary=skill.latest_version.summary,
                    category=skill.latest_version.category,
                    workflow_template_revision_alias=skill.latest_version.workflow_template_revision_alias,
                    workflow_revision_id=workflow_revision_id,
                    expected_outputs_json=_json(skill.latest_version.expected_outputs),
                    review_required=skill.latest_version.review_required,
                    estimated_cost_hint=skill.latest_version.estimated_cost_hint,
                    status="published",
                    frozen_at=utc_now(),
                )
            )
            # These tables intentionally have no ORM relationship; flush the parent
            # before adding its foreign-keyed compatibility row.
            await session.flush()
            session.add(
                CreationSkillCompatibilityRecord(
                    skill_version_id=skill.latest_version.id,
                    content_modes_json=_json(sorted(compatibility.content_modes)),
                    generation_modes_json=_json(sorted(compatibility.generation_modes)),
                    required_inputs_json=_json(sorted(compatibility.required_inputs)),
                    scopes_json=_json(sorted(compatibility.scopes)),
                    grid_storyboards_json=(
                        _json(sorted(compatibility.grid_storyboards))
                        if compatibility.grid_storyboards is not None
                        else None
                    ),
                )
            )
            changed += 1
        else:
            compatibility = await session.get(CreationSkillCompatibilityRecord, version.id)
            if compatibility is None or _stored_payload(version, compatibility) != _manifest_payload(skill):
                raise CreationSkillManifestConflict(
                    f"Frozen Creation Skill version {version.id} differs from the manifest"
                )
            workflow_revision_id = await _ensure_official_workflow_revision(
                session,
                skill,
                current_revision_id=version.workflow_revision_id,
            )
            if version.workflow_revision_id != workflow_revision_id:
                version.workflow_revision_id = workflow_revision_id
                changed += 1

    await session.commit()
    return changed


async def deactivate_creation_skill(session: AsyncSession, skill_id: str, *, actor_role: str = "user") -> bool:
    """Stop a Skill without deleting its definitions or frozen history."""

    if actor_role not in {"admin", "official"}:
        raise PermissionError("creation_skill_maintenance_forbidden")

    definition = await session.get(CreationSkillDefinitionRecord, skill_id)
    if definition is None:
        return False
    definition.active = False
    await session.commit()
    return True


async def list_creation_skills(
    session: AsyncSession,
    project: Mapping[str, object],
    available_inputs: set[str],
) -> list[dict[str, object]]:
    """Return active persisted releases with compatibility reports."""

    from lib.creation_skills import compatibility_report

    rows = (
        await session.execute(
            select(CreationSkillDefinitionRecord, CreationSkillVersionRecord, CreationSkillCompatibilityRecord)
            .join(CreationSkillVersionRecord, CreationSkillVersionRecord.skill_id == CreationSkillDefinitionRecord.id)
            .join(
                CreationSkillCompatibilityRecord,
                CreationSkillCompatibilityRecord.skill_version_id == CreationSkillVersionRecord.id,
            )
            .join(WorkflowRevision, WorkflowRevision.id == CreationSkillVersionRecord.workflow_revision_id)
            .where(
                CreationSkillDefinitionRecord.active.is_(True),
                CreationSkillVersionRecord.status == "published",
                WorkflowRevision.status == "published",
            )
            .order_by(CreationSkillDefinitionRecord.id, CreationSkillVersionRecord.version.desc())
        )
    ).all()
    latest: dict[
        str, tuple[CreationSkillDefinitionRecord, CreationSkillVersionRecord, CreationSkillCompatibilityRecord]
    ] = {}
    for definition, version, compatibility in rows:
        latest.setdefault(definition.id, (definition, version, compatibility))

    result = []
    for definition, version, compatibility in latest.values():
        skill = _version_from_records(definition, version, compatibility)
        result.append(
            {
                "id": definition.id,
                "slug": definition.slug,
                "title": version.title,
                "summary": version.summary,
                "version": version.version,
                "version_id": version.id,
                "workflow_revision_id": version.workflow_revision_id,
                "category": version.category,
                "inputs": sorted(skill.latest_version.compatibility.required_inputs),
                "outputs": list(skill.latest_version.expected_outputs),
                "review_required": version.review_required,
                "estimated_cost_hint": version.estimated_cost_hint,
                "compatibility": compatibility_report(skill, project, available_inputs),
            }
        )
    return result


async def list_creation_skill_versions(session: AsyncSession, skill_id: str) -> list[dict[str, object]]:
    """Return every persisted release, including inactive historical versions."""

    rows = (
        (
            await session.execute(
                select(CreationSkillVersionRecord)
                .where(CreationSkillVersionRecord.skill_id == skill_id)
                .order_by(CreationSkillVersionRecord.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "skill_id": row.skill_id,
            "workflow_revision_id": row.workflow_revision_id,
            "version": row.version,
            "title": row.title,
            "summary": row.summary,
            "category": row.category,
            "status": row.status,
            "frozen_at": row.frozen_at.isoformat(),
        }
        for row in rows
    ]
