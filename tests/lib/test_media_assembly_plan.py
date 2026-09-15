from __future__ import annotations

import pytest

from lib.media_assembly.plan import (
    AssemblyPlanTransitionError,
    AssemblyPlanValidationError,
    assert_transition,
    source_fingerprint,
    validate_plan_document,
)

pytestmark = pytest.mark.unit


def _document() -> dict[str, object]:
    return {
        "source_snapshot": {"episode": 1, "units": [{"id": "unit-1", "version": 2}]},
        "timeline": [
            {
                "id": "unit-1",
                "order": 0,
                "kind": "video_unit",
                "source_ref": "media/unit-1.mp4",
                "duration_seconds": 8,
                "audio_policy": "duck",
            }
        ],
        "audio": {"tracks": [{"id": "voice-1", "kind": "voiceover", "source_ref": "audio/voice.wav", "volume": 1.0}]},
        "subtitle": {"cues": [{"id": "cue-1", "text": "Hello", "start_seconds": 0, "end_seconds": 2}]},
        "packaging": {
            "cover": {"source_ref": "cover.png", "duration_seconds": 2, "fit": "cover"},
            "intro": {"text": "Episode 1", "duration_seconds": 2},
            "outro": {"text": "The End", "duration_seconds": 2},
        },
        "output_profile": {"format": "mp4", "width": 1080, "height": 1920, "fps": 30},
    }


def _assert_invalid(document: dict[str, object], code: str) -> None:
    with pytest.raises(AssemblyPlanValidationError) as exc_info:
        validate_plan_document(**document)
    assert any(error["code"] == code for error in exc_info.value.errors)


def test_valid_document_contains_all_plan_sections() -> None:
    result = validate_plan_document(**_document())
    assert result == {"valid": True, "errors": [], "warnings": []}


def test_timeline_requires_unique_contiguous_order_and_ids() -> None:
    document = _document()
    timeline = list(document["timeline"])  # type: ignore[arg-type]
    timeline.append({**timeline[0], "id": "unit-1", "order": 2})
    document["timeline"] = timeline
    with pytest.raises(AssemblyPlanValidationError) as exc_info:
        validate_plan_document(**document)
    codes = {error["code"] for error in exc_info.value.errors}
    assert {"duplicate", "non_contiguous_order"} <= codes


def test_timeline_rejects_empty_trimmed_duration_and_bad_audio_policy() -> None:
    document = _document()
    item = dict(document["timeline"][0])  # type: ignore[index]
    item.update(trim_start_seconds=4, trim_end_seconds=4, audio_policy="blend")
    document["timeline"] = [item]
    with pytest.raises(AssemblyPlanValidationError) as exc_info:
        validate_plan_document(**document)
    codes = {error["code"] for error in exc_info.value.errors}
    assert {"empty_after_trim", "invalid_audio_policy"} <= codes


def test_subtitle_cues_must_not_overlap() -> None:
    document = _document()
    document["subtitle"] = {
        "cues": [
            {"id": "cue-1", "text": "A", "start_seconds": 0, "end_seconds": 2},
            {"id": "cue-2", "text": "B", "start_seconds": 1, "end_seconds": 3},
        ]
    }
    _assert_invalid(document, "overlap")


def test_packaging_requires_structured_intro_outro_and_cover() -> None:
    document = _document()
    document["packaging"] = {
        "cover": {"source_ref": "", "duration_seconds": 0},
        "intro": {"text": "", "duration_seconds": 0},
    }
    with pytest.raises(AssemblyPlanValidationError) as exc_info:
        validate_plan_document(**document)
    codes = {error["code"] for error in exc_info.value.errors}
    assert {"string_required", "positive_number_required", "string_required"} <= codes


def test_disabled_packaging_sections_do_not_require_enabled_fields() -> None:
    document = _document()
    document["packaging"] = {
        "cover": {"enabled": False, "source": None},
        "intro": {"enabled": False, "kind": "title_card", "duration_seconds": 0},
        "outro": {"enabled": False, "kind": "end_card", "duration_seconds": 0},
    }

    result = validate_plan_document(**document)

    assert result == {"valid": True, "errors": [], "warnings": []}


def test_output_profile_only_allows_mp4() -> None:
    document = _document()
    document["output_profile"] = {"format": "mov"}
    _assert_invalid(document, "unsupported_format")


def test_fingerprint_is_independent_of_mapping_key_order() -> None:
    assert source_fingerprint({"a": 1, "b": {"x": True, "y": 2}}) == source_fingerprint(
        {"b": {"y": 2, "x": True}, "a": 1}
    )


def test_status_transitions_and_preview_gate() -> None:
    assert_transition("draft", "confirmed")
    assert_transition("confirmed", "preview_pending")
    assert_transition("preview_pending", "preview_ready")
    assert_transition("preview_ready", "render_pending")
    with pytest.raises(AssemblyPlanTransitionError):
        assert_transition("draft", "render_pending")
    with pytest.raises(AssemblyPlanTransitionError):
        assert_transition("completed", "rendering")


def test_invalid_document_shape_is_rejected() -> None:
    document = _document()
    document["timeline"] = []
    _assert_invalid(document, "not_empty")
