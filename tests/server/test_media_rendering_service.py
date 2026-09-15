from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lib.media_assembly import rendering
from server.services import media_assembly, media_rendering
from tests.lib.test_media_assembly_plan import _document

pytestmark = pytest.mark.integration


async def _create_confirmed_plan(session, *, user_id: str = "user-1") -> dict:
    created = await media_assembly.create_plan(
        session,
        user_id=user_id,
        project_name="demo",
        name="Preview",
        scope="episode",
        episode_number=1,
        **_document(),
    )
    await media_assembly.transition_plan(session, created["id"], user_id=user_id, target_status="confirmed")
    await session.commit()
    return created


async def test_successful_preview_persists_artifact_and_marks_gate(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created = await _create_confirmed_plan(async_session)
    job = await media_rendering.create_preview_job(async_session, created["id"], user_id="user-1")
    await async_session.commit()
    monkeypatch.setattr(media_rendering, "_project_root", lambda _: tmp_path)

    async def fake_render(timeline, *, output_path: Path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preview")
        return {"duration_seconds": 8.0, "width": 480, "height": 854}

    monkeypatch.setattr(media_rendering, "render_preview_pipeline", fake_render)
    result = await media_rendering.run_preview_job(async_session, job["id"], user_id="user-1")

    assert result["status"] == "succeeded"
    assert result["artifact"]["revision_number"] == 1
    plan = await media_assembly.get_plan(async_session, created["id"], user_id="user-1")
    assert plan["status"] == "preview_ready"
    assert plan["preview_revision_number"] == 1


async def test_failure_is_persisted_and_retry_consumes_execution_budget(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created = await _create_confirmed_plan(async_session)
    job = await media_rendering.create_preview_job(async_session, created["id"], user_id="user-1", max_attempts=2)
    await async_session.commit()
    monkeypatch.setattr(media_rendering, "_project_root", lambda _: tmp_path)

    async def fail_render(*args, **kwargs):
        raise rendering.RenderToolError("ffmpeg_unavailable", "ffmpeg is unavailable")

    monkeypatch.setattr(media_rendering, "render_preview_pipeline", fail_render)
    with pytest.raises(rendering.RenderToolError):
        await media_rendering.run_preview_job(async_session, job["id"], user_id="user-1")
    failed = await media_rendering.get_render_job(async_session, job["id"], user_id="user-1")
    assert failed["status"] == "failed"
    assert failed["attempt"] == 1
    assert failed["error_code"] == "ffmpeg_unavailable"

    retried = await media_rendering.retry_preview_job(async_session, job["id"], user_id="user-1")
    assert retried["status"] == "queued"
    assert retried["attempt"] == 1
    await async_session.commit()
    with pytest.raises(rendering.RenderToolError):
        await media_rendering.run_preview_job(async_session, job["id"], user_id="user-1")
    failed_again = await media_rendering.get_render_job(async_session, job["id"], user_id="user-1")
    assert failed_again["attempt"] == 2
    with pytest.raises(media_rendering.RenderJobConflictError) as exc_info:
        await media_rendering.retry_preview_job(async_session, job["id"], user_id="user-1")
    assert exc_info.value.code == "retry_limit_reached"


async def test_job_and_artifact_are_user_scoped(async_session) -> None:
    created = await _create_confirmed_plan(async_session, user_id="owner")
    job = await media_rendering.create_preview_job(async_session, created["id"], user_id="owner")
    await async_session.commit()
    with pytest.raises(media_rendering.RenderJobNotFoundError):
        await media_rendering.get_render_job(async_session, job["id"], user_id="other")


async def test_final_review_is_not_ready_without_final_artifact(async_session) -> None:
    created = await _create_confirmed_plan(async_session)
    with pytest.raises(media_rendering.FinalRenderNotReadyError):
        await media_rendering.review_final_artifact(async_session, created["id"], user_id="user-1")


async def test_subtitle_export_serializes_current_owned_revision(async_session) -> None:
    created = await _create_confirmed_plan(async_session)
    result = await media_rendering.export_subtitles(async_session, created["id"], format="vtt", user_id="user-1")
    assert result["filename"] == "subtitles.vtt"
    assert result["media_type"].startswith("text/vtt")
    assert result["content"].startswith("WEBVTT\n")
    with pytest.raises(media_assembly.AssemblyPlanNotFoundError):
        await media_rendering.export_subtitles(async_session, created["id"], format="srt", user_id="other")


async def _prepare_final_plan(session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, dict]:
    created = await _create_confirmed_plan(session)
    preview_job = await media_rendering.create_preview_job(session, created["id"], user_id="user-1")
    await session.commit()
    monkeypatch.setattr(media_rendering, "_project_root", lambda _: tmp_path)

    async def fake_preview(timeline, *, output_path: Path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preview")
        return {"duration_seconds": 8.0, "width": 480, "height": 854}

    monkeypatch.setattr(media_rendering, "render_preview_pipeline", fake_preview)
    await media_rendering.run_preview_job(session, preview_job["id"], user_id="user-1")
    await media_assembly.confirm_preview(session, created["id"], user_id="user-1", revision_number=1)
    await media_assembly.confirm_render(session, created["id"], user_id="user-1", revision_number=1)
    final_job = await media_rendering.create_final_job(session, created["id"], user_id="user-1")
    await session.commit()
    return created, final_job


async def _prepare_succeeded_final(session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, dict]:
    created, final_job = await _prepare_final_plan(session, monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    async def fake_final(timeline, *, output_path: Path, **kwargs):
        captured.update(kwargs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"final-mp4")
        return {"duration_seconds": 8.0, "width": 1080, "height": 1920}

    monkeypatch.setattr(media_rendering, "render_final_pipeline", fake_final)
    monkeypatch.setattr(
        media_rendering,
        "probe_media",
        AsyncMock(return_value={"duration_seconds": 14.0, "width": 1080, "height": 1920, "audio_present": True}),
    )
    result = await media_rendering.run_final_job(session, final_job["id"], user_id="user-1")
    return created, result


async def test_final_review_persists_snapshot_and_confirmation(async_session, monkeypatch, tmp_path: Path) -> None:
    created, final_result = await _prepare_succeeded_final(async_session, monkeypatch, tmp_path)

    monkeypatch.setattr(
        media_rendering,
        "_probe_final_artifact",
        AsyncMock(
            return_value={
                "duration_seconds": 14.0,
                "width": 1080,
                "height": 1920,
                "audio_stream_present": False,
            }
        ),
    )
    monkeypatch.setattr(media_rendering, "_detect_black_frames", AsyncMock(return_value=[]))
    monkeypatch.setattr(media_rendering, "_detect_silence_segments", AsyncMock(return_value=[]))

    async def extract_frame(artifact, source_path, *, position, timestamp_seconds):
        return {"available": True, "position": position, "timestamp_seconds": timestamp_seconds}

    monkeypatch.setattr(media_rendering, "_extract_review_frame", extract_frame)

    review = await media_rendering.review_final_artifact(async_session, created["id"], user_id="user-1")
    snapshot = review["review_snapshot"]
    assert review["status"] == "ready"
    assert review["checks"]["audio_stream"] == {"present": False, "severity": "info"}
    assert review["checks"]["timeline_duration"] == {
        "expected_seconds": 14.0,
        "actual_seconds": 14.0,
        "within_tolerance": True,
    }
    assert review["checks"]["subtitle_bounds"]["valid"] is True
    assert review["checks"]["audio_quality"]["severity"] == "info"
    assert snapshot["artifact_id"] == final_result["artifact"]["id"]
    assert snapshot["revision_number"] == 1
    assert snapshot["source_fingerprint"]
    assert snapshot["artifact_fingerprint"] == final_result["artifact"]["fingerprint"]

    confirmed = await media_rendering.confirm_final_review(
        async_session, final_result["artifact"]["id"], user_id="user-1"
    )
    assert confirmed["confirmed_by"] == "user-1"
    assert confirmed["confirmed_at"] is not None


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [("duration", "duration_mismatch"), ("black", "black_frames_detected"), ("frame", "review_frame_missing")],
)
async def test_final_review_blocks_quality_failures(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str, expected_reason: str
) -> None:
    created, final_result = await _prepare_succeeded_final(async_session, monkeypatch, tmp_path)
    duration = 15.0 if failure == "duration" else 14.0
    monkeypatch.setattr(
        media_rendering,
        "_probe_final_artifact",
        AsyncMock(
            return_value={
                "duration_seconds": duration,
                "width": 1080,
                "height": 1920,
                "audio_stream_present": True,
            }
        ),
    )
    monkeypatch.setattr(
        media_rendering,
        "_detect_black_frames",
        AsyncMock(
            return_value=[{"start_seconds": 1.0, "end_seconds": 1.5, "duration_seconds": 0.5}]
            if failure == "black"
            else []
        ),
    )
    monkeypatch.setattr(media_rendering, "_detect_silence_segments", AsyncMock(return_value=[]))

    async def extract_frame(artifact, source_path, *, position, timestamp_seconds):
        if failure == "frame" and position == "middle":
            raise media_rendering.FinalRenderReviewError("review_frame_missing", "missing frame")
        return {"available": True, "position": position, "timestamp_seconds": timestamp_seconds}

    monkeypatch.setattr(media_rendering, "_extract_review_frame", extract_frame)
    review = await media_rendering.review_final_artifact(async_session, created["id"], user_id="user-1")

    assert review["status"] == "blocked"
    assert expected_reason in review["blocking_reasons"]
    with pytest.raises(media_rendering.RenderReviewConflictError) as exc_info:
        await media_rendering.confirm_final_review(async_session, final_result["artifact"]["id"], user_id="user-1")
    assert exc_info.value.code == "review_blocked"


async def test_final_review_warnings_and_info_do_not_block_confirmation(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created, final_result = await _prepare_succeeded_final(async_session, monkeypatch, tmp_path)
    monkeypatch.setattr(
        media_rendering,
        "_probe_final_artifact",
        AsyncMock(
            return_value={
                "duration_seconds": 14.0,
                "width": 1080,
                "height": 1920,
                "audio_stream_present": True,
            }
        ),
    )
    monkeypatch.setattr(
        media_rendering,
        "_detect_black_frames",
        AsyncMock(return_value=[{"start_seconds": 0.0, "end_seconds": 0.2, "duration_seconds": 0.2}]),
    )
    monkeypatch.setattr(
        media_rendering,
        "_detect_silence_segments",
        AsyncMock(return_value=[{"start_seconds": 0.0, "end_seconds": 6.0, "duration_seconds": 6.0}]),
    )
    monkeypatch.setattr(
        media_rendering,
        "_detect_audio_metrics",
        AsyncMock(
            return_value={
                "mean_volume_db": -28.0,
                "max_volume_db": -8.0,
                "integrated_lufs": -28.0,
                "clipped_samples": 0,
            }
        ),
    )

    async def extract_frame(artifact, source_path, *, position, timestamp_seconds):
        return {"available": True, "position": position, "timestamp_seconds": timestamp_seconds}

    monkeypatch.setattr(media_rendering, "_extract_review_frame", extract_frame)
    review = await media_rendering.review_final_artifact(async_session, created["id"], user_id="user-1")

    assert review["status"] == "ready"
    assert review["blocking_reasons"] == []
    assert "edge_black_frames_detected" in review["warning_reasons"]
    assert "long_silence_detected" in review["warning_reasons"]
    assert "loudness_out_of_range" in review["warning_reasons"]
    await media_rendering.confirm_final_review(async_session, final_result["artifact"]["id"], user_id="user-1")


async def test_final_review_blocks_audio_clipping(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created, final_result = await _prepare_succeeded_final(async_session, monkeypatch, tmp_path)
    monkeypatch.setattr(
        media_rendering,
        "_probe_final_artifact",
        AsyncMock(
            return_value={
                "duration_seconds": 14.0,
                "width": 1080,
                "height": 1920,
                "audio_stream_present": True,
            }
        ),
    )
    monkeypatch.setattr(media_rendering, "_detect_black_frames", AsyncMock(return_value=[]))
    monkeypatch.setattr(media_rendering, "_detect_silence_segments", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        media_rendering,
        "_detect_audio_metrics",
        AsyncMock(
            return_value={
                "mean_volume_db": -12.0,
                "max_volume_db": 0.0,
                "integrated_lufs": -16.0,
                "clipped_samples": 4,
            }
        ),
    )

    async def extract_frame(artifact, source_path, *, position, timestamp_seconds):
        return {"available": True, "position": position, "timestamp_seconds": timestamp_seconds}

    monkeypatch.setattr(media_rendering, "_extract_review_frame", extract_frame)
    review = await media_rendering.review_final_artifact(async_session, created["id"], user_id="user-1")

    assert review["status"] == "blocked"
    assert "audio_clipping_detected" in review["blocking_reasons"]
    with pytest.raises(media_rendering.RenderReviewConflictError) as exc_info:
        await media_rendering.confirm_final_review(async_session, final_result["artifact"]["id"], user_id="user-1")
    assert exc_info.value.code == "review_blocked"


async def test_final_review_confirmation_is_owner_scoped(async_session, monkeypatch, tmp_path: Path) -> None:
    created, final_result = await _prepare_succeeded_final(async_session, monkeypatch, tmp_path)
    with pytest.raises(media_rendering.RenderArtifactNotFoundError):
        await media_rendering.confirm_final_review(async_session, final_result["artifact"]["id"], user_id="other")
    with pytest.raises(media_assembly.AssemblyPlanNotFoundError):
        await media_rendering.review_final_artifact(async_session, created["id"], user_id="other")


async def test_final_job_success_persists_final_artifact_and_completes_plan(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created, final_job = await _prepare_final_plan(async_session, monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    async def fake_final(timeline, *, output_path: Path, **kwargs):
        captured.update(kwargs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"final-mp4")
        return {"duration_seconds": 8.0, "width": 1080, "height": 1920}

    monkeypatch.setattr(media_rendering, "render_final_pipeline", fake_final)
    monkeypatch.setattr(
        media_rendering,
        "probe_media",
        __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value={"duration_seconds": 14.0, "width": 1080, "height": 1920, "audio_present": True}
        ),
    )
    result = await media_rendering.run_final_job(async_session, final_job["id"], user_id="user-1")

    assert captured["packaging"] == _document()["packaging"]
    assert result["kind"] == "final"
    assert result["status"] == "succeeded"
    assert result["artifact"]["kind"] == "final"
    assert result["artifact"]["relative_path"].startswith("render_artifacts/final/revision-1/")
    plan = await media_assembly.get_plan(async_session, created["id"], user_id="user-1")
    assert plan["status"] == "completed"


async def test_final_job_failure_is_persisted_and_can_be_retried(
    async_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created, final_job = await _prepare_final_plan(async_session, monkeypatch, tmp_path)

    async def fail_final(*args, **kwargs):
        raise rendering.RenderToolError("final_ffmpeg_failed", "ffmpeg failed")

    monkeypatch.setattr(media_rendering, "render_final_pipeline", fail_final)
    with pytest.raises(rendering.RenderToolError):
        await media_rendering.run_final_job(async_session, final_job["id"], user_id="user-1")

    failed = await media_rendering.get_render_job(async_session, final_job["id"], user_id="user-1")
    assert failed["kind"] == "final"
    assert failed["status"] == "failed"
    assert failed["attempt"] == 1
    assert failed["error_code"] == "final_ffmpeg_failed"
    plan = await media_assembly.get_plan(async_session, created["id"], user_id="user-1")
    assert plan["status"] == "failed"

    retried = await media_rendering.retry_final_job(async_session, final_job["id"], user_id="user-1")
    assert retried["status"] == "queued"
    assert retried["attempt"] == 1
    plan = await media_assembly.get_plan(async_session, created["id"], user_id="user-1")
    assert plan["status"] == "render_pending"


async def test_final_job_requires_both_confirmations(async_session) -> None:
    created = await _create_confirmed_plan(async_session)
    with pytest.raises(media_rendering.RenderJobConflictError) as exc_info:
        await media_rendering.create_final_job(async_session, created["id"], user_id="user-1")
    assert exc_info.value.code == "preview_revision_required"

    preview_job = await media_rendering.create_preview_job(async_session, created["id"], user_id="user-1")
    await async_session.commit()
    with pytest.raises(media_rendering.RenderJobConflictError):
        await media_rendering.create_final_job(async_session, created["id"], user_id="user-1")
    assert preview_job["kind"] == "preview"
