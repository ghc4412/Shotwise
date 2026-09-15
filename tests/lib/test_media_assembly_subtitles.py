from __future__ import annotations

import pytest

from lib.media_assembly.subtitles import (
    SubtitleCue,
    SubtitleValidationError,
    generate_srt,
    generate_vtt,
    normalize_cues,
)

pytestmark = pytest.mark.unit


def test_generate_srt_uses_stable_numbering_and_millisecond_timestamps() -> None:
    text = generate_srt(
        [
            SubtitleCue(0, 1.25, "你好\n世界"),
            {"start_seconds": 2.5, "end_seconds": 65.125, "text": "Next"},
        ]
    )

    assert text == ("1\n00:00:00,000 --> 00:00:01,250\n你好\n世界\n\n2\n00:00:02,500 --> 00:01:05,125\nNext\n")


def test_generate_vtt_contains_header_and_identifier() -> None:
    text = generate_vtt([SubtitleCue(1.5, 2.75, "Cue", identifier="cue-1")])

    assert text == "WEBVTT\n\ncue-1\n00:00:01.500 --> 00:00:02.750\nCue\n"


def test_subtitles_reject_invalid_or_overlapping_cues() -> None:
    with pytest.raises(SubtitleValidationError, match="greater than"):
        normalize_cues([SubtitleCue(1, 1, "bad")])
    with pytest.raises(SubtitleValidationError, match="overlaps"):
        normalize_cues([SubtitleCue(0, 2, "one"), SubtitleCue(1, 3, "two")])
    with pytest.raises(SubtitleValidationError, match="non-empty"):
        generate_srt([SubtitleCue(0, 1, " ")])


def test_subtitles_normalize_line_endings_and_reject_nul() -> None:
    normalized = normalize_cues([SubtitleCue(0, 1, "a\r\nb\r")])
    assert normalized[0].text == "a\nb\n"

    with pytest.raises(SubtitleValidationError, match="NUL"):
        generate_vtt([SubtitleCue(0, 1, "bad\x00text")])
