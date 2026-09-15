from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.media_assembly import rendering

pytestmark = pytest.mark.unit


async def test_preview_uses_direct_process_args_and_validates_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "preview.mp4"
    calls: list[list[str]] = []
    manifests: list[str] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if "concat" in args and "-i" in args:
            manifests.append(Path(args[args.index("-i") + 1]).read_text(encoding="utf-8"))
        if "ffprobe" in args[0]:
            return b'{"format":{"duration":"1.25"},"streams":[{"codec_type":"video","width":480,"height":854}]}', b""
        Path(args[-1]).write_bytes(b"preview")
        return b"", b""

    monkeypatch.setattr(rendering, "_run_process", fake_run)
    result = await rendering.render_low_resolution_preview(
        [{"source_ref": "unit.mp4"}],
        project_root=tmp_path,
        output_path=output,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
    )

    assert result == {"duration_seconds": 1.25, "width": 480, "height": 854}
    assert output.read_bytes() == b"preview"
    assert calls[0][0] == "ffmpeg"
    assert calls[0][calls[0].index("-map") + 1] == "0:v:0?"
    assert calls[0][calls[0].index("-map") + 3] == "0:a:0?"
    assert "shell" not in calls[0]
    assert not (tmp_path / ".preview-work").exists()


def test_manifest_rejects_project_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(rendering.RenderToolError) as exc_info:
        rendering.build_concat_manifest(
            [{"source_ref": "../outside.mp4"}],
            project_root=tmp_path,
            manifest_path=tmp_path / "manifest.ffconcat",
        )
    assert exc_info.value.code == "source_file_missing"


async def test_preview_rejects_invalid_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        if "ffprobe" in args[0]:
            return json.dumps({"format": {"duration": "0"}, "streams": []}).encode(), b""
        Path(args[-1]).write_bytes(b"preview")
        return b"", b""

    monkeypatch.setattr(rendering, "_run_process", fake_run)
    with pytest.raises(rendering.RenderToolError) as exc_info:
        await rendering.render_low_resolution_preview(
            [{"source_ref": "unit.mp4"}],
            project_root=tmp_path,
            output_path=tmp_path / "preview.mp4",
            ffmpeg_path="ffmpeg",
            ffprobe_path="ffprobe",
        )
    assert exc_info.value.code == "preview_probe_invalid"


async def test_packaging_generates_cover_and_text_clips_before_concat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"image")
    output = tmp_path / "final.mp4"
    calls: list[list[str]] = []
    manifests: list[str] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if "concat" in args and "-i" in args:
            manifests.append(Path(args[args.index("-i") + 1]).read_text(encoding="utf-8"))
        if "ffprobe" in args[0]:
            return b'{"format":{"duration":"7"},"streams":[{"codec_type":"video","width":1080,"height":1920}]}', b""
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"generated")
        return b"", b""

    monkeypatch.setattr(rendering, "_run_process", fake_run)
    result = await rendering.render_video(
        [{"source_ref": "unit.mp4"}],
        project_root=tmp_path,
        output_path=output,
        width=1080,
        height=1920,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        packaging={
            "cover": {"source_ref": "cover.png", "duration_seconds": 2, "fit": "cover"},
            "intro": {"text": "Episode 1", "duration_seconds": 2},
            "outro": {"text": "The End", "duration_seconds": 2},
        },
    )

    assert result["duration_seconds"] == 7
    assert sum("-loop" in call for call in calls) == 1
    assert sum("drawtext=" in " ".join(call) for call in calls) == 2
    manifest = manifests[0]
    assert "unit.mp4" in manifest
    assert "packaged-cover.mp4" in manifest
