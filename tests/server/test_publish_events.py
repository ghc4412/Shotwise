from __future__ import annotations

import pytest

import lib.publish_events as publish_events

pytestmark = pytest.mark.unit


def test_build_publish_job_change_is_a_non_blocking_refresh_signal() -> None:
    assert publish_events.build_publish_job_change(" job-1 ") == {
        "entity_type": "publish_job",
        "action": "publish_job_updated",
        "entity_id": "job-1",
        "label": "job-1",
        "focus": None,
        "important": False,
    }


def test_emit_publish_job_events_skips_empty_ids_and_preserves_order(monkeypatch) -> None:
    captured = []

    def fake_emit(project_name, changes, *, source):
        captured.append((project_name, changes, source))

    monkeypatch.setattr(publish_events, "emit_project_change_batch", fake_emit)

    publish_events.emit_publish_job_events(
        " demo ",
        ("job-1", "", "job-1"),
        source="worker",
    )

    assert captured == [
        (
            "demo",
            [
                publish_events.build_publish_job_change("job-1"),
                publish_events.build_publish_job_change("job-1"),
            ],
            "worker",
        )
    ]


def test_emit_publish_job_event_swallows_event_delivery_errors(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("closed")

    monkeypatch.setattr(publish_events, "emit_project_change_batch", fail)
    publish_events.emit_publish_job_event("demo", "job-1")


def test_empty_publish_job_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="publish_job_id"):
        publish_events.build_publish_job_change(" ")
