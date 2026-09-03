"""Public tests for the security-first declarative endpoint seam."""

from __future__ import annotations

import pytest

from lib.custom_provider.endpoints import (
    EndpointDeclarationValidationError,
    normalize_endpoint_response,
    parse_endpoint_declaration,
    render_endpoint_declaration,
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
