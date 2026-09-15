"""Unit tests for deterministic final-artifact quality checks."""

import pytest

from lib.media_assembly.review import (
    audio_level_check,
    audio_quality_check,
    classify_black_frame_edges,
    expected_timeline_duration,
    parse_audio_metrics_log,
    parse_silencedetect_log,
    subtitle_bounds_check,
)

pytestmark = pytest.mark.unit


def test_subtitle_bounds_reports_out_of_range_and_overlap() -> None:
    result = subtitle_bounds_check(
        {
            "cues": [
                {"id": "a", "start_seconds": 0, "end_seconds": 2, "text": "A"},
                {"id": "b", "start_seconds": 1.5, "end_seconds": 4, "text": "B"},
            ]
        },
        duration_seconds=3,
    )

    assert result["valid"] is False
    assert {item["code"] for item in result["items"]} == {"overlap", "out_of_bounds"}


def test_silencedetect_parser_pairs_completed_and_open_segments() -> None:
    log = """
        [silencedetect] silence_start: 0
        [silencedetect] silence_end: 1.250 | silence_duration: 1.250
        [silencedetect] silence_start: 4.5
    """

    assert parse_silencedetect_log(log) == [
        {"start_seconds": 0.0, "end_seconds": 1.25, "duration_seconds": 1.25},
        {"start_seconds": 4.5, "end_seconds": None, "duration_seconds": None},
    ]


def test_audio_quality_closes_open_silence_at_render_end() -> None:
    result = audio_quality_check(
        audio_stream_present=True,
        silence_segments=[{"start_seconds": 2.0, "end_seconds": None, "duration_seconds": None}],
        duration_seconds=8.0,
    )

    assert result["severity"] == "warning"
    assert result["issues"] == [{"code": "long_silence_detected", "severity": "warning"}]


def test_audio_metrics_parser_accepts_ffmpeg_histogram_clipping_count() -> None:
    metrics = parse_audio_metrics_log("[Parsed_volumedetect_0] histogram_0db: 7")

    assert metrics["clipped_samples"] == 7


def test_audio_quality_distinguishes_missing_audio_and_full_silence() -> None:
    missing = audio_quality_check(audio_stream_present=False, silence_segments=[], duration_seconds=8)
    silent = audio_quality_check(
        audio_stream_present=True,
        silence_segments=[{"start_seconds": 0, "end_seconds": 8, "duration_seconds": 8}],
        duration_seconds=8,
    )

    assert missing["severity"] == "info"
    assert missing["abnormal"] is False
    assert silent["severity"] == "blocking"
    assert silent["abnormal"] is True


def test_expected_timeline_duration_applies_trim() -> None:
    assert (
        expected_timeline_duration(
            [
                {
                    "duration_seconds": 10,
                    "trim_start_seconds": 1,
                    "trim_end_seconds": 2,
                },
                {"duration_seconds": 3},
            ]
        )
        == 10
    )


def test_black_frame_classification_marks_edges_and_middle() -> None:
    result = classify_black_frame_edges(
        [
            {"start_seconds": 0, "end_seconds": 0.4, "duration_seconds": 0.4},
            {"start_seconds": 2, "end_seconds": 2.4, "duration_seconds": 0.4},
            {"start_seconds": 5, "end_seconds": 6, "duration_seconds": 1},
        ],
        duration_seconds=6,
    )

    assert [item["edge"] for item in result["segments"]] == ["opening", "middle", "ending"]
    assert result["full_duration"] is False


def test_audio_metrics_parser_and_level_check_classify_loudness_and_clipping() -> None:
    metrics = parse_audio_metrics_log(
        """
        mean_volume: -20.0 dB
        max_volume: -0.05 dB
        [Parsed_ebur128_0 @ 0x0]
          I:           -24.0 LUFS
        number of clipped samples: 3
        """
    )

    assert metrics == {
        "mean_volume_db": -20.0,
        "max_volume_db": -0.05,
        "integrated_lufs": -24.0,
        "clipped_samples": 3,
    }
    result = audio_level_check(metrics)
    assert result["severity"] == "blocking"
    assert {issue["code"] for issue in result["issues"]} == {
        "loudness_out_of_range",
        "audio_clipping_detected",
    }


def test_edge_black_frames_are_warning_but_middle_black_frames_are_blocking() -> None:
    opening = classify_black_frame_edges([{"start_seconds": 0, "end_seconds": 0.2}], duration_seconds=10)
    middle = classify_black_frame_edges([{"start_seconds": 3, "end_seconds": 3.2}], duration_seconds=10)

    assert opening["severity"] == "warning"
    assert middle["severity"] == "blocking"
