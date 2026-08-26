"""Rollout configuration, metric privacy, and legacy media fallback checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib import feature_flags
from server import media_index_cli
from server.services.media_indexing import scan_project_media_assets

pytestmark = pytest.mark.unit


def test_rollout_configuration_rejects_invalid_and_unknown_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOTWISE_FEATURE_OFFICIAL_CREATION_SKILLS", "maybe")
    monkeypatch.setenv("SHOTWISE_FEATURE_UNEXPECTED", "true")

    result = feature_flags.validate_rollout_configuration()

    assert result["valid"] is False
    errors = result["errors"]
    assert isinstance(errors, list)
    assert any("OFFICIAL_CREATION_SKILLS" in error for error in errors)
    assert any("UNEXPECTED" in error for error in errors)
    assert "maybe" not in json.dumps(result)


def test_creation_lifecycle_metrics_are_categorical_and_non_sensitive() -> None:
    feature_flags.reset_creation_metrics()
    events = (
        "skill_open",
        "skill_preview",
        "skill_start",
        "skill_success",
        "skill_failure",
        "skill_cancel",
        "skill_incompatible",
    )
    try:
        for event in events:
            feature_flags.record_creation_metric(
                event,
                creation_skill_version_id="official:novel:v1",
                project_generation_mode="storyboard",
                resource_type="shot",
                reason="generation_mode_mismatch" if event == "skill_incompatible" else None,
                outcome="incompatible" if event == "skill_incompatible" else "completed",
            )

        serialized = json.dumps(feature_flags.creation_metric_snapshot(), ensure_ascii=False)
        assert all(event in serialized for event in events)
        assert "G:\\Shotwise" not in serialized
        assert "/projects/" not in serialized
        assert "prompt text" not in serialized
    finally:
        feature_flags.reset_creation_metrics()


def test_metric_dimensions_strip_paths_and_free_form_content() -> None:
    feature_flags.reset_creation_metrics()
    try:
        feature_flags.record_creation_metric(
            "skill_open",
            creation_skill_version_id="G:\\Shotwise\\project.json",
            resource_type="prompt text",
            reason="/projects/demo",
        )

        serialized = json.dumps(feature_flags.creation_metric_snapshot(), ensure_ascii=False)
        assert "Shotwise" not in serialized
        assert "prompt text" not in serialized
        assert "/projects/demo" not in serialized
    finally:
        feature_flags.reset_creation_metrics()


def test_media_index_dry_run_respects_disabled_flag_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    before = sorted(path.relative_to(project_root).as_posix() for path in project_root.rglob("*"))
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "0")

    result = scan_project_media_assets("project", project_root, dry_run=True)

    assert result["enabled"] is False
    assert result["dry_run"] is True
    after = sorted(path.relative_to(project_root).as_posix() for path in project_root.rglob("*"))
    assert after == before


def test_media_index_cli_rejects_retry_and_dry_run_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["media_index_cli", "project", ".", "--dry-run", "--retry"])

    with pytest.raises(SystemExit) as exc_info:
        media_index_cli.main()

    assert exc_info.value.code == 2
