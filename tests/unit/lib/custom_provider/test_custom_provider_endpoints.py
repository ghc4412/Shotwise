"""Public tests for the security-first declarative endpoint seam."""

from __future__ import annotations

import pytest

from lib.custom_provider.endpoints import (
    EndpointDeclarationValidationError,
    normalize_endpoint_response,
    parse_endpoint_declaration,
    render_endpoint_artifact_url,
    render_endpoint_declaration,
    render_endpoint_poll,
    render_poll_pointer,
    validate_endpoint_declaration,
)

pytestmark = pytest.mark.unit


def _declaration(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "method": "POST",
        "path": "/v1/videos/{model}",
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "body": {"/prompt": "prompt", "/options/duration": "duration"},
        "response": {"job_id": "/id", "status": "/state", "result_url": "/output/0/url"},
    }
    value.update(overrides)
    return value


def test_parse_validate_render_and_normalize_a_limited_declaration() -> None:
    declaration = parse_endpoint_declaration(_declaration())

    assert validate_endpoint_declaration(declaration) is declaration
    rendered = render_endpoint_declaration(
        declaration,
        {"model": "example-video", "prompt": "a lighthouse at dusk", "duration": 6},
    )
    assert rendered.method == "POST"
    assert rendered.path == "/v1/videos/example-video"
    assert rendered.headers == {"Accept": "application/json", "Content-Type": "application/json"}
    assert rendered.body == {
        "prompt": "a lighthouse at dusk",
        "options": {"duration": 6},
    }
    assert normalize_endpoint_response(
        declaration,
        {"id": "task-42", "state": "queued", "output": [{"url": "https://media.example/video.mp4"}]},
    ) == {
        "job_id": "task-42",
        "status": "queued",
        "result_url": "https://media.example/video.mp4",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (_declaration(method="PATCH"), "method"),
        (_declaration(path="https://untrusted.example/v1/videos"), "path"),
        (_declaration(path="/v1/../admin"), "path"),
        (_declaration(headers={"Authorization": "Bearer unsafe"}), "header"),
        (_declaration(body={"/prompt": "{{ user.prompt }}"}), "body"),
        (_declaration(body={"/input": "prompt", "/input/text": "text"}), "body"),
        (_declaration(response={"job_id": "$.id"}), "response"),
    ],
)
def test_parse_rejects_unbounded_transport_or_mapping_shapes(raw: dict[str, object], expected: str) -> None:
    with pytest.raises(EndpointDeclarationValidationError, match=expected):
        parse_endpoint_declaration(raw)


def test_render_requires_every_declared_input_and_normalize_requires_every_response_path() -> None:
    declaration = parse_endpoint_declaration(_declaration())

    with pytest.raises(EndpointDeclarationValidationError, match="input"):
        render_endpoint_declaration(declaration, {"model": "example-video", "prompt": "missing duration"})
    with pytest.raises(EndpointDeclarationValidationError, match="response"):
        normalize_endpoint_response(declaration, {"id": "task-42", "state": "queued", "output": []})


def test_headers_are_fixed_and_renderer_rejects_undeclared_runtime_headers() -> None:
    declaration = parse_endpoint_declaration(_declaration())

    with pytest.raises(EndpointDeclarationValidationError, match="header"):
        render_endpoint_declaration(
            declaration,
            {"model": "example-video", "prompt": "prompt", "duration": 6, "headers": {"X-Unsafe": "1"}},
        )


def test_capability_declaration_is_filtered_by_existing_synthesis() -> None:
    from lib.custom_provider.capabilities import synthesize_video_capabilities_with_declaration

    declaration = parse_endpoint_declaration(
        _declaration(capability_overrides={"max_reference_images": 2, "last_frame": True})
    )
    caps, applied = synthesize_video_capabilities_with_declaration(
        endpoint="openai-video",
        model_id="sora-2",
        declaration=declaration,
        overrides={"max_reference_images": 3},
    )

    assert caps.max_reference_images == 3
    assert caps.last_frame is False
    assert applied == {"max_reference_images": 3}


def _poll_declaration(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "method": "POST",
        "path": "/prompt",
        "body_template": {"prompt": {"9": {"inputs": {"text": "{prompt}", "seed": "seed={seed}"}}}},
        "response": {},
        "poll": {
            "path": "/history/{job_id}",
            "job_id": "/prompt_id",
            "status": "/{job_id}/status/status_str",
            "done_value": "success",
            "failed_value": "error",
            "result": "/{job_id}/outputs/9/images/0",
            "artifact_url": "/view?filename={filename}&subfolder={subfolder}&type={type}",
            "interval_seconds": 0.05,
            "timeout_seconds": 5,
        },
    }
    value.update(overrides)
    return value


def test_body_template_embeds_whole_values_and_interpolates_scalars() -> None:
    declaration = parse_endpoint_declaration(_poll_declaration())

    rendered = render_endpoint_declaration(declaration, {"model": "comfy", "prompt": "a cat", "seed": 7})

    assert rendered.body == {"prompt": {"9": {"inputs": {"text": "a cat", "seed": "seed=7"}}}}


def test_poll_renderers_use_job_id_pointer_escaping_and_artifact_fields() -> None:
    declaration = parse_endpoint_declaration(_poll_declaration())

    poll_request = render_endpoint_poll(declaration, {"model": "comfy", "job_id": "job-1"})

    assert poll_request is not None
    assert poll_request.path == "/history/job-1"
    assert render_poll_pointer("/{job_id}/status", {"job_id": "a/b"}) == "/a~1b/status"
    assert declaration.poll is not None
    assert (
        render_endpoint_artifact_url(declaration.poll, {"filename": "a b.png", "subfolder": "", "type": "output"})
        == "/view?filename=a%20b.png&subfolder=&type=output"
    )


def test_body_template_rejects_unsafe_placeholders_and_combination() -> None:
    with pytest.raises(EndpointDeclarationValidationError, match="mutually exclusive"):
        parse_endpoint_declaration(_declaration(body_template={"text": "{prompt}"}))
    with pytest.raises(EndpointDeclarationValidationError, match="placeholder"):
        parse_endpoint_declaration(_declaration(body={}, body_template={"text": "{unknown}"}))
    with pytest.raises(EndpointDeclarationValidationError, match="placeholder"):
        parse_endpoint_declaration(_declaration(body={}, body_template={"text": "{{prompt}}"}))


@pytest.mark.parametrize(
    "poll",
    [
        {"path": "/history/{job_id}", "job_id": "/prompt_id", "status": "/s", "done_value": "ok", "extra": 1},
        {"path": "/history/{job_id}?x=1", "job_id": "/prompt_id", "status": "/s", "done_value": "ok"},
        {
            "path": "/history/{job_id}",
            "job_id": "/prompt_id",
            "status": "/s",
            "done_value": "ok",
            "interval_seconds": 0,
        },
        {
            "path": "/history/{job_id}",
            "job_id": "/prompt_id",
            "status": "/s",
            "done_value": "ok",
            "timeout_seconds": 99999,
        },
        {
            "path": "/history/{job_id}",
            "job_id": "/prompt_id",
            "status": "/s",
            "done_value": "ok",
            "artifact_url": "/view?filename={filename}",
            "headers": {"X-Test": "1"},
        },
    ],
)
def test_poll_rejects_invalid_shapes(poll: dict[str, object]) -> None:
    with pytest.raises(EndpointDeclarationValidationError):
        parse_endpoint_declaration(_poll_declaration(poll=poll))


def test_poll_requires_non_null_done_value() -> None:
    missing = {"path": "/history/{job_id}", "job_id": "/prompt_id", "status": "/s"}
    with pytest.raises(EndpointDeclarationValidationError, match="done_value"):
        parse_endpoint_declaration(_poll_declaration(poll=missing))
    with pytest.raises(EndpointDeclarationValidationError, match="done_value"):
        parse_endpoint_declaration(_poll_declaration(poll={**missing, "done_value": None}))
