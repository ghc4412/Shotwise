from __future__ import annotations

import pytest
from sqlalchemy import select

from lib.creation_skills import OFFICIAL_CREATION_SKILLS
from lib.db.models.creation_skill import (
    CreationSkillCompatibilityRecord,
    CreationSkillDefinitionRecord,
    CreationSkillVersionRecord,
)
from lib.db.models.workflow import WorkflowRevision
from server.services.creation_skill_catalog import (
    CreationSkillManifestConflict,
    deactivate_creation_skill,
    list_creation_skill_versions,
    sync_official_creation_skills,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_catalog_sync_is_idempotent_and_publishes_manifest(async_session):
    first = await sync_official_creation_skills(async_session)
    second = await sync_official_creation_skills(async_session)

    definitions = (await async_session.execute(select(CreationSkillDefinitionRecord))).scalars().all()
    versions = (await async_session.execute(select(CreationSkillVersionRecord))).scalars().all()
    compatibilities = (await async_session.execute(select(CreationSkillCompatibilityRecord))).scalars().all()

    assert first == len(OFFICIAL_CREATION_SKILLS) * 2
    assert second == 0
    assert {definition.id for definition in definitions} == {skill.id for skill in OFFICIAL_CREATION_SKILLS}
    assert len(versions) == len(OFFICIAL_CREATION_SKILLS)
    assert len(compatibilities) == len(OFFICIAL_CREATION_SKILLS)
    assert {version.status for version in versions} == {"published"}
    assert {version.workflow_revision_id for version in versions} <= {
        revision.id
        for revision in (await async_session.execute(select(WorkflowRevision))).scalars().all()
        if revision.status == "published"
    }
    assert all(version.workflow_revision_id for version in versions)


@pytest.mark.asyncio
async def test_catalog_sync_rejects_mutating_a_frozen_release(async_session):
    await sync_official_creation_skills(async_session)
    version = (await async_session.execute(select(CreationSkillVersionRecord))).scalars().first()
    assert version is not None
    original_title = version.title
    version.title = original_title + " changed"
    await async_session.commit()

    with pytest.raises(CreationSkillManifestConflict):
        await sync_official_creation_skills(async_session)


@pytest.mark.asyncio
async def test_deactivation_preserves_historical_versions(async_session):
    await sync_official_creation_skills(async_session)
    skill_id = OFFICIAL_CREATION_SKILLS[0].id

    assert await deactivate_creation_skill(async_session, skill_id, actor_role="admin") is True
    history = await list_creation_skill_versions(async_session, skill_id)

    assert history
    assert history[0]["status"] == "published"

    definition = await async_session.get(CreationSkillDefinitionRecord, skill_id)
    assert definition is not None
    assert definition.active is False


@pytest.mark.asyncio
async def test_ordinary_user_cannot_mutate_official_skill_catalog(async_session):
    await sync_official_creation_skills(async_session)

    with pytest.raises(PermissionError, match="creation_skill_maintenance_forbidden"):
        await deactivate_creation_skill(async_session, OFFICIAL_CREATION_SKILLS[0].id)


@pytest.mark.asyncio
async def test_catalog_sync_rejects_a_release_bound_to_unpublished_revision(async_session):
    await sync_official_creation_skills(async_session)
    version = (await async_session.execute(select(CreationSkillVersionRecord))).scalars().first()
    assert version is not None
    revision = await async_session.get(WorkflowRevision, version.workflow_revision_id)
    assert revision is not None
    revision.status = "draft"
    await async_session.commit()

    with pytest.raises(CreationSkillManifestConflict, match="unpublished Workflow Revision"):
        await sync_official_creation_skills(async_session)
