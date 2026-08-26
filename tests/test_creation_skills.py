from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from lib.creation_skills import OFFICIAL_CREATION_SKILLS, list_official_creation_skills


def test_official_catalog_contains_only_official_immutable_skills() -> None:
    assert len(OFFICIAL_CREATION_SKILLS) >= 21
    assert all(skill.official and skill.latest_version.version == 1 for skill in OFFICIAL_CREATION_SKILLS)
    assert all(
        skill.latest_version.workflow_template_revision_alias.startswith("official:")
        for skill in OFFICIAL_CREATION_SKILLS
    )


def test_catalog_explains_route_incompatibility_without_changing_project_mode() -> None:
    project = {"content_mode": "drama", "generation_mode": "storyboard"}
    entries = {skill.id: result for skill, result in list_official_creation_skills(project, {"document"})}

    assert entries["reference-image-video"] == "generation_mode_incompatible"
    assert project["generation_mode"] == "storyboard"


def test_catalog_reports_missing_required_input() -> None:
    project = {"content_mode": "drama", "generation_mode": "storyboard"}
    entries = {skill.id: result for skill, result in list_official_creation_skills(project, set())}

    assert entries["novel-to-drama"] == "missing_inputs:document"


def test_official_catalog_covers_marketplace_categories():
    categories = {skill.latest_version.category for skill in OFFICIAL_CREATION_SKILLS}

    assert len(OFFICIAL_CREATION_SKILLS) >= 21
    assert {
        "推荐",
        "专业影视",
        "商业广告",
        "短剧爽剧",
        "动漫游戏",
        "音乐MV",
        "自媒体创作",
        "通用技能",
        "发现",
    } <= categories
