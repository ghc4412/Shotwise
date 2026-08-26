from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lib.feature_flags import (
    creation_metric_snapshot,
    feature_audit_snapshot,
    feature_enabled,
    feature_snapshot,
    record_creation_metric,
    reset_creation_metrics,
)
from lib.media_catalog import media_index_enabled
from server.routers import features as feature_router

pytestmark = pytest.mark.unit

_ENV_NAMES = (
    "SHOTWISE_FEATURE_OFFICIAL_CREATION_SKILLS",
    "SHOTWISE_MEDIA_ASSET_INDEX",
    "SHOTWISE_FEATURE_MEDIA_LIBRARY",
    "SHOTWISE_FEATURE_CREATION_PLAN",
    "SHOTWISE_FEATURE_CREATIVE_BOARD",
    "SHOTWISE_FEATURE_CONTEXT_AGENT",
)


def test_rollout_flags_use_safe_defaults(monkeypatch):
    for env_name in _ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)

    assert feature_snapshot() == {
        "official_creation_skills": True,
        "media_asset_index": False,
        "media_library": True,
        "creation_plan": True,
        "creative_board": True,
        "context_agent": True,
    }


def test_rollout_flags_are_explicit_and_media_index_preserves_legacy_switch(monkeypatch):
    assert feature_enabled("creation_plan") is True
    assert feature_enabled("media_asset_index") is False
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    assert media_index_enabled() is True
    monkeypatch.setenv("SHOTWISE_FEATURE_CREATION_PLAN", "0")
    assert feature_enabled("creation_plan") is False


def test_flag_off_is_explicit_and_does_not_change_other_flags(monkeypatch):
    monkeypatch.setenv("SHOTWISE_FEATURE_CREATIVE_BOARD", "off")
    monkeypatch.setenv("SHOTWISE_FEATURE_CONTEXT_AGENT", "on")

    assert feature_enabled("creative_board") is False
    assert feature_enabled("context_agent") is True


def test_invalid_configuration_fails_closed_without_exposing_raw_value(monkeypatch):
    monkeypatch.setenv("SHOTWISE_FEATURE_CREATION_PLAN", "definitely-not-a-boolean")

    assert feature_enabled("creation_plan") is False
    audit = feature_audit_snapshot()
    assert audit["invalid_flags"] == ["creation_plan"]
    assert audit["invalid_count"] == 1
    flags = audit["flags"]
    assert isinstance(flags, dict)
    assert flags["creation_plan"] == {
        "enabled": False,
        "source": "invalid",
        "valid": False,
    }
    assert "definitely-not-a-boolean" not in str(audit)


def test_feature_snapshot_contains_only_known_public_flags(monkeypatch):
    monkeypatch.setenv("SHOTWISE_FEATURE_CREATIVE_BOARD", "off")
    snapshot = feature_snapshot()
    assert snapshot["creative_board"] is False
    assert "AUTH_PASSWORD" not in snapshot


def test_creation_metrics_aggregate_only_bounded_non_sensitive_dimensions():
    reset_creation_metrics()
    record_creation_metric(
        "skill_open",
        creation_skill_version_id="novel-to-drama:v1",
        project_generation_mode="storyboard",
        resource_type="manuscript",
    )
    record_creation_metric(
        "skill_open",
        creation_skill_version_id="novel-to-drama:v1",
        project_generation_mode="storyboard",
        resource_type="manuscript",
    )
    record_creation_metric(
        "skill_incompatible",
        creation_skill_version_id="reference-image-video:v1",
        project_generation_mode="storyboard",
        resource_type="video",
        reason="generation_mode_not_supported",
        outcome="alternative_skill",
    )

    metrics = creation_metric_snapshot()
    assert metrics == {
        "items": [
            {
                "event": "skill_incompatible",
                "creation_skill_version_id": "reference-image-video:v1",
                "project_generation_mode": "storyboard",
                "resource_type": "video",
                "reason": "generation_mode_not_supported",
                "outcome": "alternative_skill",
                "count": 1,
            },
            {
                "event": "skill_open",
                "creation_skill_version_id": "novel-to-drama:v1",
                "project_generation_mode": "storyboard",
                "resource_type": "manuscript",
                "reason": "",
                "outcome": "",
                "count": 2,
            },
        ]
    }
    assert "prompt" not in str(metrics).lower()
    assert "physical_path" not in str(metrics).lower()
    reset_creation_metrics()


def test_creation_metrics_reject_unknown_event_and_sanitize_dimensions():
    reset_creation_metrics()
    with pytest.raises(ValueError):
        record_creation_metric("raw_prompt")

    record_creation_metric(
        "skill_failure",
        creation_skill_version_id="prompt text",
        project_generation_mode="storyboard",
        resource_type="unknown",
        outcome="not-a-result",
    )
    items = creation_metric_snapshot()["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["creation_skill_version_id"] == ""
    assert item["resource_type"] == ""
    assert item["outcome"] == ""
    reset_creation_metrics()


@pytest.mark.asyncio
async def test_feature_metrics_aggregates_non_content_compatibility_data(monkeypatch):
    fake_session = cast(AsyncSession, object())

    async def fake_compatibility_metrics(session: AsyncSession) -> dict[str, object]:
        assert session is fake_session
        return {
            "items": [
                {
                    "creation_skill_version_id": "reference-image-video:v1",
                    "project_generation_mode": "storyboard",
                    "reason": "generation_mode_not_supported",
                    "outcome": "alternative_skill",
                    "count": 2,
                }
            ]
        }

    monkeypatch.setattr(feature_router.creation_plan_service, "compatibility_metrics", fake_compatibility_metrics)
    result = await feature_router.get_feature_metrics(fake_session)

    assert result["compatibility"] == {
        "items": [
            {
                "creation_skill_version_id": "reference-image-video:v1",
                "project_generation_mode": "storyboard",
                "reason": "generation_mode_not_supported",
                "outcome": "alternative_skill",
                "count": 2,
            }
        ]
    }
    serialized = str(result).lower()
    assert "prompt_snapshot" not in serialized
    assert "manuscript" not in serialized
    assert "physical_path" not in serialized


@pytest.mark.asyncio
async def test_feature_metrics_includes_creation_rollout_events(monkeypatch):
    reset_creation_metrics()
    record_creation_metric(
        "skill_cancel",
        creation_skill_version_id="novel-to-drama:v1",
        project_generation_mode="storyboard",
        outcome="cancelled",
    )
    fake_session = cast(AsyncSession, object())

    async def fake_compatibility_metrics(session: AsyncSession) -> dict[str, object]:
        assert session is fake_session
        return {"items": []}

    monkeypatch.setattr(feature_router.creation_plan_service, "compatibility_metrics", fake_compatibility_metrics)
    result = await feature_router.get_feature_metrics(fake_session)

    assert result["creation"] == {
        "items": [
            {
                "event": "skill_cancel",
                "creation_skill_version_id": "novel-to-drama:v1",
                "project_generation_mode": "storyboard",
                "resource_type": "",
                "reason": "",
                "outcome": "cancelled",
                "count": 1,
            }
        ]
    }
    reset_creation_metrics()
