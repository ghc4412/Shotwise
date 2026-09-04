import pytest

from lib.episode_duration_plan import (
    DurationPlanningStrategy,
    EpisodeDurationPlanner,
    ShotDurationInput,
    read_episode_duration_plan,
)


@pytest.mark.unit
def test_equal_plan_only_changes_unlocked_ungenerated_shots() -> None:
    planner = EpisodeDurationPlanner()
    plan = planner.build_plan(
        target_seconds=24,
        shots=[
            ShotDurationInput("locked", current_seconds=5, locked=True, supported_durations=(4, 5, 6)),
            ShotDurationInput("generated", current_seconds=6, generated=True, supported_durations=(4, 6, 8)),
            ShotDurationInput("a", current_seconds=4, supported_durations=(4, 6, 8)),
            ShotDurationInput("b", current_seconds=4, supported_durations=(4, 6, 8)),
        ],
        strategy=DurationPlanningStrategy.EQUAL,
    )

    assert plan.target_seconds == 24
    assert plan.by_shot_id["locked"].requested_seconds == 5
    assert plan.by_shot_id["generated"].requested_seconds == 6
    assert plan.by_shot_id["a"].allocated_seconds == 7
    assert plan.by_shot_id["b"].allocated_seconds == 6
    assert plan.by_shot_id["a"].requested_seconds == 6
    assert plan.by_shot_id["a"].clamp_reason == "nearest_supported_duration"


@pytest.mark.unit
def test_provider_max_clamp_is_explicit() -> None:
    plan = EpisodeDurationPlanner().build_plan(
        target_seconds=10,
        shots=[ShotDurationInput("a", current_seconds=5, supported_durations=(2, 4, 6))],
    )

    allocation = plan.by_shot_id["a"]
    assert allocation.allocated_seconds == 10
    assert allocation.requested_seconds == 6
    assert allocation.clamp_reason == "provider_max_duration"


@pytest.mark.unit
def test_preview_and_apply_do_not_change_locked_or_generated_shots() -> None:
    planner = EpisodeDurationPlanner()
    shots = [
        ShotDurationInput("locked", current_seconds=5, locked=True, supported_durations=(5, 10)),
        ShotDurationInput("generated", current_seconds=5, generated=True, supported_durations=(5, 10)),
        ShotDurationInput("open", current_seconds=5, supported_durations=(5, 10)),
    ]
    plan = planner.build_plan(target_seconds=20, shots=shots)

    preview = planner.preview_replan(shots, plan)

    assert {change.shot_id for change in preview.changes} == {"open"}
    assert preview.changes[0].from_seconds == 5
    assert preview.changes[0].to_seconds == 10
    assert planner.apply_confirmed_plan(shots, plan) == {"open": 10}


@pytest.mark.unit
def test_proportional_and_manual_overrides_are_supported() -> None:
    planner = EpisodeDurationPlanner()
    proportional = planner.build_plan(
        target_seconds=15,
        shots=[
            ShotDurationInput("a", current_seconds=4, weight=2, supported_durations=(1, 5, 10)),
            ShotDurationInput("b", current_seconds=4, weight=1, supported_durations=(1, 5, 10)),
        ],
        strategy=DurationPlanningStrategy.PROPORTIONAL,
    )
    manual = planner.build_plan(
        target_seconds=15,
        shots=[
            ShotDurationInput("a", current_seconds=4, supported_durations=(1, 5, 10)),
            ShotDurationInput("b", current_seconds=4, supported_durations=(1, 5, 10)),
        ],
        strategy=DurationPlanningStrategy.MANUAL,
        manual_allocations={"a": 10, "b": 5},
    )

    assert proportional.by_shot_id["a"].allocated_seconds == 10
    assert proportional.by_shot_id["b"].allocated_seconds == 5
    assert manual.by_shot_id["a"].allocated_seconds == 10
    assert manual.by_shot_id["b"].allocated_seconds == 5


@pytest.mark.unit
def test_target_shorter_than_fixed_shots_is_rejected() -> None:
    with pytest.raises(ValueError, match="fixed shot duration total"):
        EpisodeDurationPlanner().build_plan(
            target_seconds=9,
            shots=[
                ShotDurationInput("locked", current_seconds=5, locked=True, supported_durations=(5,)),
                ShotDurationInput("generated", current_seconds=5, generated=True, supported_durations=(5,)),
            ],
        )


@pytest.mark.unit
def test_missing_provider_durations_fail_loudly() -> None:
    with pytest.raises(ValueError, match="supported_durations must not be empty"):
        EpisodeDurationPlanner().build_plan(
            target_seconds=8,
            shots=[ShotDurationInput("open", current_seconds=8, supported_durations=())],
        )


@pytest.mark.unit
def test_read_episode_duration_plan_supports_script_metadata_and_legacy_ad_target() -> None:
    configured = read_episode_duration_plan(
        {"target_duration": 60},
        {
            "metadata": {
                "episode_duration_plan": {
                    "target_seconds": 24,
                    "strategy": "manual",
                    "manual_allocations": {"a": 10, "b": 14},
                }
            }
        },
    )
    assert configured is not None
    assert configured.target_seconds == 24
    assert configured.strategy is DurationPlanningStrategy.MANUAL
    assert configured.manual_allocations == {"a": 10, "b": 14}

    legacy = read_episode_duration_plan({"target_duration": 60}, {})
    assert legacy is not None
    assert legacy.target_seconds == 60
    assert legacy.strategy is DurationPlanningStrategy.EQUAL


@pytest.mark.unit
def test_request_for_item_ignores_generated_and_locked_items() -> None:
    planner = EpisodeDurationPlanner()
    shots = [
        ShotDurationInput("open", 4, (4, 6, 8)),
        ShotDurationInput("locked", 4, (4, 6, 8), locked=True),
        ShotDurationInput("generated", 4, (4, 6, 8), generated=True),
    ]
    plan = planner.build_plan(target_seconds=20, shots=shots)

    assert planner.requested_seconds_for("open", plan) == 8
    assert planner.requested_seconds_for("locked", plan) == 4
    assert planner.requested_seconds_for("generated", plan) == 4
