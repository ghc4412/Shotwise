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
