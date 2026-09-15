from __future__ import annotations

from pathlib import Path

import pytest

from lib.media_assembly.audio import (
    AudioMixConfig,
    AudioMixValidationError,
    AudioTrack,
    VolumePoint,
    build_audio_mix_command,
    resolve_project_media_path,
)

pytestmark = pytest.mark.unit


def test_default_policy_ducks_original_audio() -> None:
    args = build_audio_mix_command(
        "ffmpeg",
        video_path=Path("unit.mp4"),
        output_path=Path("mixed.mp4"),
        tracks=(AudioTrack(Path("voice.wav"), "narration"),),
    )

    assert args[0] == "ffmpeg"
    assert "shell" not in args
    assert "volume=0.35" in args[args.index("-filter_complex") + 1]
    assert "amix=inputs=2" in args[args.index("-filter_complex") + 1]


def test_keep_and_mute_policies_are_explicit() -> None:
    keep_args = build_audio_mix_command(
        "ffmpeg",
        video_path=Path("unit.mp4"),
        output_path=Path("keep.mp4"),
        config=AudioMixConfig(original_policy="keep"),
    )
    mute_args = build_audio_mix_command(
        "ffmpeg",
        video_path=Path("unit.mp4"),
        output_path=Path("mute.mp4"),
        config=AudioMixConfig(original_policy="mute"),
    )

    assert "volume=1" in keep_args[keep_args.index("-filter_complex") + 1]
    assert "-an" in mute_args
    assert "-filter_complex" not in mute_args


def test_fades_and_volume_envelope_are_encoded_and_validated() -> None:
    args = build_audio_mix_command(
        "ffmpeg",
        video_path=Path("unit.mp4"),
        output_path=Path("mixed.mp4"),
        config=AudioMixConfig(
            original_policy="keep",
            duration_seconds=10,
            fade_in_seconds=1,
            fade_out_seconds=2,
            volume_envelope=(VolumePoint(0, 0.2), VolumePoint(5, 1.0)),
        ),
        tracks=(
            AudioTrack(
                Path("music.mp3"),
                "bgm",
                start_seconds=2,
                duration_seconds=6,
                fade_in_seconds=1,
                fade_out_seconds=1,
            ),
        ),
    )
    filter_graph = args[args.index("-filter_complex") + 1]

    assert "afade=t=in:st=0:d=1" in filter_graph
    assert "afade=t=out:st=5:d=1" in filter_graph
    assert "adelay=2000:all=1" in filter_graph
    assert "eval=frame" in filter_graph
    assert args[args.index("-t") + 1] == "10"

    with pytest.raises(AudioMixValidationError, match="cannot exceed duration"):
        build_audio_mix_command(
            "ffmpeg",
            video_path=Path("unit.mp4"),
            output_path=Path("bad.mp4"),
            config=AudioMixConfig(duration_seconds=2, fade_in_seconds=2, fade_out_seconds=1),
        )


def test_project_media_path_rejects_escape(tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"video")
    assert resolve_project_media_path(tmp_path, "unit.mp4") == source.resolve()

    with pytest.raises(AudioMixValidationError, match="outside the project"):
        resolve_project_media_path(tmp_path, "../outside.mp4")


def test_track_fade_out_requires_track_or_output_duration() -> None:
    with pytest.raises(AudioMixValidationError, match="duration_seconds is required"):
        build_audio_mix_command(
            "ffmpeg",
            video_path=Path("unit.mp4"),
            output_path=Path("bad.mp4"),
            tracks=(AudioTrack(Path("voice.wav"), "dialogue", fade_out_seconds=1),),
        )
