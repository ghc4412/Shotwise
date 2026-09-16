from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.media_assembly import rendering

pytestmark = pytest.mark.unit

CLIP_PROBE_ENTRIES = "format=duration:stream=codec_type"
OUTPUT_PROBE_ENTRIES = "format=duration:stream=codec_type,width,height"


def _is_clip_probe(args: list[str]) -> bool:
    """Match the per-input ffprobe used to normalise heterogeneous sources."""
    return "ffprobe" in args[0] and args[args.index("-show_entries") + 1] == CLIP_PROBE_ENTRIES


def _is_output_probe(args: list[str]) -> bool:
    """Match the ffprobe run against the rendered file."""
    return "ffprobe" in args[0] and args[args.index("-show_entries") + 1] == OUTPUT_PROBE_ENTRIES


def _clip_probe_json(*, audio: bool = True, duration: str = "1.25") -> bytes:
    streams: list[dict[str, str]] = [{"codec_type": "video"}]
    if audio:
        streams.append({"codec_type": "audio"})
    return json.dumps({"format": {"duration": duration}, "streams": streams}).encode()


def _output_probe_json(*, duration: str = "1.25", width: int = 480, height: int = 854) -> bytes:
    return json.dumps(
        {
            "format": {"duration": duration},
            "streams": [
                {"codec_type": "video", "width": width, "height": height},
                {"codec_type": "audio"},
            ],
        }
    ).encode()


def _render_call(calls: list[list[str]]) -> list[str]:
    return next(call for call in calls if call[0] == "ffmpeg" and "-filter_complex" in call)


def _inputs(call: list[str]) -> list[Path]:
    return [Path(value).resolve() for index, value in enumerate(call) if index > 0 and call[index - 1] == "-i"]


def test_timeline_clips_reject_project_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(rendering.RenderToolError) as exc_info:
        rendering.resolve_timeline_clips([{"source_ref": "../outside.mp4"}], project_root=tmp_path)
    assert exc_info.value.code == "source_file_missing"


async def test_preview_uses_direct_process_args_and_validates_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "preview.mp4"
    calls: list[list[str]] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if _is_clip_probe(args):
            return _clip_probe_json(), b""
        if _is_output_probe(args):
            return _output_probe_json(), b""
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
    render_call = _render_call(calls)
    assert render_call[0] == "ffmpeg"
    filter_graph = render_call[render_call.index("-filter_complex") + 1]
    assert "concat=n=1:v=1:a=1" in filter_graph
    assert render_call[render_call.index("-map") + 1] == "[outv]"
    assert render_call[render_call.index("-map") + 3] == "[outa]"
    assert "-f" not in render_call
    assert "shell" not in render_call
    assert not (tmp_path / ".preview-work").exists()


async def test_preview_rejects_invalid_output_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        if _is_clip_probe(args):
            return _clip_probe_json(), b""
        if _is_output_probe(args):
            return b'{"format":{"duration":"0"},"streams":[]}', b""
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


async def test_preview_rejects_unreadable_clip_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        if _is_clip_probe(args):
            return b'{"streams":[]}', b""
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
    assert exc_info.value.code == "source_probe_invalid"


async def test_preview_requires_known_length_for_silent_clip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        if _is_clip_probe(args):
            return b'{"format":{"duration":"0"},"streams":[{"codec_type":"video"}]}', b""
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
    assert exc_info.value.code == "source_duration_invalid"


async def test_mixed_sources_normalise_into_one_concat_filtergraph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wide = tmp_path / "wide.mp4"
    wide.write_bytes(b"wide")
    tall = tmp_path / "tall.mp4"
    tall.write_bytes(b"tall")
    calls: list[list[str]] = []
    clip_probes = {
        "wide.mp4": _clip_probe_json(audio=True, duration="3.0"),
        "tall.mp4": _clip_probe_json(audio=False, duration="4.0"),
    }

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if _is_clip_probe(args):
            return clip_probes[Path(args[-1]).name], b""
        if _is_output_probe(args):
            return _output_probe_json(duration="7.0"), b""
        Path(args[-1]).write_bytes(b"preview")
        return b"", b""

    monkeypatch.setattr(rendering, "_run_process", fake_run)
    await rendering.render_low_resolution_preview(
        [{"source_ref": "wide.mp4"}, {"source_ref": "tall.mp4"}],
        project_root=tmp_path,
        output_path=tmp_path / "preview.mp4",
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
    )

    render_call = _render_call(calls)
    assert _inputs(render_call) == [wide.resolve(), tall.resolve()]
    filter_graph = render_call[render_call.index("-filter_complex") + 1]
    assert filter_graph.count("scale=480:854:force_original_aspect_ratio=decrease") == 2
    assert filter_graph.count("format=yuv420p") == 2
    assert "aresample=48000" in filter_graph
    assert "anullsrc=channel_layout=stereo:sample_rate=48000:d=4.000000" in filter_graph
    assert "concat=n=2:v=1:a=1" in filter_graph
    assert "-f" not in render_call


async def test_packaging_generates_cover_and_text_clips_before_concat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"image")
    output = tmp_path / "final.mp4"
    calls: list[list[str]] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if _is_clip_probe(args):
            return _clip_probe_json(duration="7"), b""
        if _is_output_probe(args):
            return _output_probe_json(duration="7", width=1080, height=1920), b""
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
    render_call = _render_call(calls)
    names = [path.name for path in _inputs(render_call)]
    assert names == ["packaged-cover.mp4", "packaged-intro.mp4", "unit.mp4", "packaged-outro.mp4"]
    assert "concat=n=4:v=1:a=1" in render_call[render_call.index("-filter_complex") + 1]


async def test_disabled_packaging_sections_are_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "unit.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "preview.mp4"
    calls: list[list[str]] = []

    async def fake_run(args: list[str], **_: object) -> tuple[bytes, bytes]:
        calls.append(args)
        if _is_clip_probe(args):
            return _clip_probe_json(), b""
        if _is_output_probe(args):
            return _output_probe_json(), b""
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"preview")
        return b"", b""

    monkeypatch.setattr(rendering, "_run_process", fake_run)
    result = await rendering.render_low_resolution_preview(
        [{"source_ref": "unit.mp4"}],
        project_root=tmp_path,
        output_path=output,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        packaging={
            "cover": {"enabled": False, "source": None},
            "intro": {"enabled": False, "duration_seconds": 0.0, "kind": "title_card"},
            "outro": {"enabled": False, "duration_seconds": 0.0, "kind": "end_card"},
        },
    )

    assert result == {"duration_seconds": 1.25, "width": 480, "height": 854}
    assert sum("-loop" in call for call in calls) == 0
    assert not any("drawtext=" in " ".join(call) for call in calls)
    render_call = _render_call(calls)
    assert _inputs(render_call) == [source.resolve()]
    assert "concat=n=1:v=1:a=1" in render_call[render_call.index("-filter_complex") + 1]
