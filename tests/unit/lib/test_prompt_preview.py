from __future__ import annotations

import pytest

from lib.prompt_preview import PROMPT_PREVIEW_PAYLOAD_KEY, build_enqueue_prompt_preview


@pytest.mark.unit
def test_enqueue_preview_captures_safe_admission_inputs_without_credentials() -> None:
    preview = build_enqueue_prompt_preview(
        project_name="demo",
        task_type="video",
        media_type="video",
        resource_id="shot-1",
        script_file="episode_1.json",
        provider_id="custom-1",
        payload={
            "prompt": {"action": "walk", "camera_motion": "pan"},
            "video_provider_i2v": "custom-1/model-a",
            "api_key": "should-not-be-copied",
            "duration_seconds": 6,
            "resolution": "720p",
        },
    )

    request = preview["requests"][0]
    assert preview["source"] == "enqueue_snapshot"
    assert request["shape"] == "structured"
    assert request["provider"] == "custom-1"
    assert request["model"] == "model-a"
    assert request["duration_seconds"] == 6
    assert "api_key" not in request["request_summary"]
    assert PROMPT_PREVIEW_PAYLOAD_KEY not in request["request_summary"]


@pytest.mark.unit
def test_enqueue_preview_redacts_nested_sensitive_fields_and_url_parameters() -> None:
    preview = build_enqueue_prompt_preview(
        project_name="demo",
        task_type="video",
        media_type="video",
        resource_id="shot-1",
        script_file="episode_1.json",
        provider_id="provider",
        payload={
            "prompt": {
                "scene": "https://cdn.example.test/render?token=secret&foo=bar#fragment-secret",
                "credentials": {"api_key": "sk-secret", "nested": "keep"},
                "items": [{"authorization": "Bearer secret", "url": "https://example.test/a?id=123"}],
            },
            "references": [
                {
                    "kind": "image",
                    "label": "ref",
                    "url": "https://cdn.example.test/image.png?signature=secret",
                }
            ],
            "warnings": ["https://example.test/warn?token=secret"],
        },
    )

    request = preview["requests"][0]
    assert "sk-secret" not in request["original_prompt"]
    assert "Bearer secret" not in request["original_prompt"]
    assert "secret" not in request["original_prompt"]
    assert "token=%5BREDACTED%5D" in request["original_prompt"]
    assert "signature=%5BREDACTED%5D" in request["references"][0]["value"]
    assert "token=%5BREDACTED%5D" in request["warnings"][0]


@pytest.mark.unit
def test_enqueue_preview_bounds_persisted_summary_strings_and_collections() -> None:
    long_text = "x" * 10_000
    preview = build_enqueue_prompt_preview(
        project_name=long_text,
        task_type=long_text,
        media_type=long_text,
        resource_id=long_text,
        script_file=long_text,
        provider_id=long_text,
        payload={
            "prompt": long_text,
            "references": ["ref"] * 100,
            "capability_adjustments": [long_text] * 100,
            "warnings": [long_text] * 100,
        },
    )

    request = preview["requests"][0]
    assert len(request["original_prompt"]) <= 4096
    assert len(request["effective_prompt"]) <= 4096
    assert len(request["request_summary"]["project_name"]) <= 256
    assert len(request["request_summary"]["script_file"]) <= 512
    assert len(request["provider"]) <= 256
    assert len(request["id"]) <= 256
    assert len(request["references"]) <= 32
    assert len(request["capability_adjustments"]) <= 32
    assert len(request["warnings"]) <= 32
    assert all(len(item) <= 512 for item in request["capability_adjustments"])
    assert all(len(item) <= 512 for item in request["warnings"])
