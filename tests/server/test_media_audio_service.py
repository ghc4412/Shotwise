from __future__ import annotations

from pathlib import Path

import pytest

from lib.media_assembly.audio import AudioMixConfig, AudioTrack
from lib.media_assembly.rendering import RenderToolError
from server.services import media_audio

pytestmark = pytest.mark.unit


async def test_mix_audio_resolves_paths_and_runs_ffmpeg_without_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = tmp_path / "unit.mp4"
    voice = tmp_path / "voice.wav"
    video.write_bytes(b"video")
    voice.write_bytes(b"voice")
    calls: list[list[str]] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        Path(args[-1]).write_bytes(b"mixed")
        return b"", b""

    monkeypatch.setattr(media_audio, "_run_process", fake_run)
    result = await media_audio.mix_audio(
        project_root=tmp_path,
        video_path="unit.mp4",
        output_path="renders/mixed.mp4",
        tracks=(AudioTrack(Path("voice.wav"), "narration"),),
        config=AudioMixConfig(original_policy="duck"),
        ffmpeg_path="ffmpeg",
    )

    assert result["output_path"] == (tmp_path / "renders/mixed.mp4").resolve()
    assert result["size_bytes"] == 5
    assert calls[0][0] == "ffmpeg"
    assert calls[0][-1] == str((tmp_path / "renders/mixed.mp4").resolve())
    assert "shell" not in calls[0]


async def test_mix_audio_rejects_output_escape_before_process(tmp_path: Path) -> None:
    video = tmp_path / "unit.mp4"
    video.write_bytes(b"video")

    with pytest.raises(ValueError, match="outside the project"):
        await media_audio.mix_audio(
            project_root=tmp_path,
            video_path="unit.mp4",
            output_path="../mixed.mp4",
            ffmpeg_path="ffmpeg",
        )


async def test_mix_audio_surfaces_missing_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video = tmp_path / "unit.mp4"
    video.write_bytes(b"video")

    async def fake_run(*args: object, **kwargs: object) -> tuple[bytes, bytes]:
        return b"", b""

    monkeypatch.setattr(media_audio, "_run_process", fake_run)
    with pytest.raises(RenderToolError) as exc_info:
        await media_audio.mix_audio(
            project_root=tmp_path,
            video_path="unit.mp4",
            output_path="mixed.mp4",
            original_audio_present=False,
            ffmpeg_path="ffmpeg",
        )
    assert exc_info.value.code == "audio_output_missing"
