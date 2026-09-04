import pytest

from lib.episode_duration_adapters import EpisodeDurationTaskAdapter
from lib.episode_duration_plan import DurationPlanningStrategy, ShotDurationInput


@pytest.mark.unit
def test_plan_requests_only_include_unlocked_ungenerated_items() -> None:
    shots = [
        ShotDurationInput("locked", 5, (4, 6, 8), locked=True),
        ShotDurationInput("generated", 6, (4, 6, 8), generated=True),
        ShotDurationInput("open", 4, (4, 6, 8)),
    ]

    plan, requests = EpisodeDurationTaskAdapter().plan_requests(
        target_seconds=20,
        shots=shots,
        strategy=DurationPlanningStrategy.EQUAL,
    )

    assert plan.by_shot_id["open"].allocated_seconds == 9
    assert [(request.resource_id, request.requested_seconds) for request in requests] == [("open", 8)]


@pytest.mark.unit
def test_plan_requests_report_provider_clamp_without_mutating_inputs() -> None:
    shots = [ShotDurationInput("open", 4, (4, 6, 8))]
    before = list(shots)

    _plan, requests = EpisodeDurationTaskAdapter().plan_requests(
        target_seconds=10,
        shots=shots,
    )

    assert requests[0].requested_seconds == 8
    assert requests[0].allocated_seconds == 10
    assert requests[0].clamp_reason == "provider_max_duration"
    assert requests[0].as_task_payload() == {"requested_seconds": 8, "duration_seconds": 8}
    assert shots == before


@pytest.mark.unit
def test_plan_item_requests_preserve_script_mappings_and_detect_generated_video() -> None:
    items = [
        {"shot_id": "open", "duration_seconds": 4},
        {"shot_id": "locked", "duration_seconds": 4, "duration_locked": True},
        {"shot_id": "done", "duration_seconds": 4, "generated_assets": {"video_clip": "done.mp4"}},
    ]
    before = [dict(item) for item in items]

    plan, requests = EpisodeDurationTaskAdapter().plan_item_requests(
        target_seconds=20,
        items=items,
        id_field="shot_id",
        supported_durations=(4, 6, 8),
    )

    assert plan.by_shot_id["locked"].requested_seconds == 4
    assert [request.resource_id for request in requests] == ["open"]
    assert items == before


@pytest.mark.unit
def test_plan_requests_reject_duplicate_resource_ids() -> None:
    with pytest.raises(ValueError, match="shot_id values must be unique"):
        EpisodeDurationTaskAdapter().plan_requests(
            target_seconds=10,
            shots=[
                ShotDurationInput("same", 5, (5,)),
                ShotDurationInput("same", 5, (5,)),
            ],
        )
