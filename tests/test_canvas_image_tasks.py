"""Independent Creative Board image-task contracts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from lib.image_backends.base import ImageCapability, ImageGenerationRequest, ImageGenerationResult
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import generate
from server.services import canvas_image_tasks
from server.services.media_assets import list_project_media_assets
from tests.auth_deps import AUTH_DEPENDENCIES

pytestmark = pytest.mark.unit


class _FakeImageBackend:
    """Image backend stub that writes a tiny PNG to ``request.output_path``."""

    name = "fake"
    model = "fake"
    capabilities = {ImageCapability.IMAGE_TO_IMAGE, ImageCapability.TEXT_TO_IMAGE}

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        Image.new("RGBA", (8, 8), (200, 100, 50, 255)).save(request.output_path, format="PNG")
        return ImageGenerationResult(image_path=request.output_path, provider="fake", model="fake")


class _FakeGenerator:
    def __init__(self, backend):
        self._backend = backend

    async def generate_image_output_async(
        self, *, prompt, output_path, reference_images, aspect_ratio, image_size, resource_id
    ):
        await self._backend.generate(
            ImageGenerationRequest(
                prompt=prompt,
                output_path=output_path,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            )
        )
        return output_path


class _FakeCtxImage:
    resolution = None


class _FakeCtx:
    def __init__(self, backend):
        self.generator = _FakeGenerator(backend)
        self.image = _FakeCtxImage()


class _FakeQueue:
    def __init__(self):
        self.calls = []

    async def enqueue_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": f"task-{len(self.calls)}", "deduped": False}


class _FakePM:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.project = {"characters": {"Alice": {"character_sheet": "characters/Alice.png"}}}

    def load_project(self, project_name):
        return self.project

    def get_project_path(self, project_name):
        return self.project_path


def _client(monkeypatch, fake_pm, fake_queue):
    monkeypatch.setattr(generate, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(generate, "get_generation_queue", lambda: fake_queue)
    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(generate.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app, raise_server_exceptions=False)


def test_canvas_image_split_enqueues_independent_grid_task(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    queue = _FakeQueue()
    client = _client(monkeypatch, _FakePM(project_path), queue)

    with client:
        response = client.post(
            "/api/v1/projects/demo/canvas-images/split",
            json={
                "source_kind": "project",
                "resource_type": "character",
                "resource_id": "Alice",
                "rows": 3,
                "cols": 2,
                "include_split_lines": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"success": True, "task_id": "task-1", "deduped": False}
    assert queue.calls[0] == {
        "project_name": "demo",
        "task_type": "canvas_image_split",
        "media_type": "image",
        "resource_id": "character:Alice",
        "payload": {
            "prompt": "canvas_image_split",
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "rows": 3,
            "cols": 2,
            "include_split_lines": True,
        },
        "source": "webui",
        "user_id": "default",
        "provider_id": "",
    }


def test_canvas_image_split_rejects_invalid_grid_without_creating_task(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    queue = _FakeQueue()
    client = _client(monkeypatch, _FakePM(project_path), queue)

    with client:
        response = client.post(
            "/api/v1/projects/demo/canvas-images/split",
            json={
                "source_kind": "project",
                "resource_type": "character",
                "resource_id": "Alice",
                "rows": 1,
                "cols": 2,
            },
        )

    assert response.status_code == 400
    assert queue.calls == []


@pytest.mark.asyncio
async def test_canvas_image_split_executor_preserves_source_and_registers_cells(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    source = Image.new("RGB", (10, 8))
    pixels = source.load()
    for y in range(8):
        for x in range(10):
            pixels[x, y] = (x * 10, y * 20, 100)
    source.save(image_path, format="PNG")
    source_bytes = image_path.read_bytes()
    fake_pm = _FakePM(project_path)
    monkeypatch.setattr(canvas_image_tasks, "get_project_manager", lambda: fake_pm)
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    result = await canvas_image_tasks.execute_canvas_image_split_task(
        "demo",
        "character:Alice",
        {
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "rows": 2,
            "cols": 2,
            "include_split_lines": False,
        },
        user_id="default",
        task_id="task-grid",
    )

    assert result["operation"] == "canvas_image_split"
    assert result["rows"] == 2
    assert result["cols"] == 2
    assert result["include_split_lines"] is False
    assert image_path.read_bytes() == source_bytes
    assert len(result["cells"]) == 4
    assert [(cell["row"], cell["col"], cell["width"], cell["height"]) for cell in result["cells"]] == [
        (0, 0, 5, 4),
        (0, 1, 5, 4),
        (1, 0, 5, 4),
        (1, 1, 5, 4),
    ]
    assert [cell["index"] for cell in result["cells"]] == [0, 1, 2, 3]
    for cell in result["cells"]:
        cell_path = project_path / cell["file_path"]
        assert cell_path.is_file()
        with Image.open(cell_path) as image:
            assert image.size == (5, 4)
        assert cell["media_asset_id"]

    indexed = list_project_media_assets(project_id="demo", project_root=project_path)
    assert len(indexed["items"]) == 4
    assert {item["origin"] for item in indexed["items"]} == {"extracted"}


def test_canvas_image_advanced_enqueues_without_reusing_grid_records(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    queue = _FakeQueue()
    client = _client(monkeypatch, _FakePM(project_path), queue)

    with client:
        response = client.post(
            "/api/v1/projects/demo/canvas-images/advanced",
            json={
                "source_kind": "project",
                "resource_type": "character",
                "resource_id": "Alice",
                "operation": "canvas_image_panorama",
                "instruction": "preserve the subject",
            },
        )

    assert response.status_code == 200
    assert queue.calls[0]["task_type"] == "canvas_image_panorama"
    assert queue.calls[0]["resource_id"] == "character:Alice"
    assert queue.calls[0]["payload"] == {
        "prompt": "canvas_image_panorama",
        "source_kind": "project",
        "resource_type": "character",
        "resource_id": "Alice",
        "operation": "canvas_image_panorama",
        "instruction": "preserve the subject",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_count"),
    [
        ("canvas_image_panorama", 1),
        ("canvas_image_angles", 4),
        ("canvas_image_layers", 3),
        ("canvas_image_hd", 1),
        ("canvas_image_outpaint", 1),
        ("canvas_image_redraw", 1),
        ("canvas_image_erase", 1),
        ("canvas_image_cutout", 1),
    ],
)
async def test_canvas_image_advanced_executor_routes_ai_operations_through_i2i_and_preserves_source(
    tmp_path, monkeypatch, operation, expected_count
):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    source = Image.new("RGBA", (12, 8), (20, 40, 60, 255))
    source.save(image_path, format="PNG")
    source_bytes = image_path.read_bytes()
    fake_pm = _FakePM(project_path)
    backend = _FakeImageBackend()

    async def _fake_resolve(*args, **kwargs):
        return _FakeCtx(backend)

    monkeypatch.setattr(canvas_image_tasks, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(canvas_image_tasks, "resolve_generation_context", _fake_resolve)
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    result = await canvas_image_tasks.execute_canvas_image_task(
        "demo",
        "character:Alice",
        {
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "operation": operation,
            "count": 4 if operation == "canvas_image_angles" else None,
        },
        task_id=f"task-{operation}",
    )

    assert result["operation"] == operation
    assert image_path.read_bytes() == source_bytes
    outputs = result.get("outputs")
    assert isinstance(outputs, list)
    assert len(outputs) == expected_count
    assert all(output.get("media_asset_id") for output in outputs)
    for output in outputs:
        assert (project_path / output["file_path"]).is_file()


@pytest.mark.asyncio
async def test_canvas_image_region_ai_operations_return_full_frame_and_preserve_unselected_pixels(
    tmp_path, monkeypatch
):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    source = Image.new("RGBA", (12, 8), (20, 40, 60, 255))
    source.putpixel((0, 0), (1, 2, 3, 255))
    source.save(image_path, format="PNG")
    fake_pm = _FakePM(project_path)
    backend = _FakeImageBackend()

    async def _fake_resolve(*args, **kwargs):
        return _FakeCtx(backend)

    monkeypatch.setattr(canvas_image_tasks, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(canvas_image_tasks, "resolve_generation_context", _fake_resolve)
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    result = await canvas_image_tasks.execute_canvas_image_task(
        "demo",
        "character:Alice",
        {
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "operation": "canvas_image_redraw",
            "instruction": "change the selected area",
            "region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        },
        task_id="task-region-redraw",
    )

    output_path = project_path / result["outputs"][0]["file_path"]
    with Image.open(output_path) as output:
        assert output.size == source.size
        assert output.getpixel((0, 0)) == (1, 2, 3, 255)
        assert output.getpixel((6, 4)) == (200, 100, 50, 255)


@pytest.mark.asyncio
async def test_canvas_image_outpaint_expands_canvas_and_preserves_source_region(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    source = Image.new("RGBA", (12, 8), (20, 40, 60, 255))
    source.putpixel((0, 0), (1, 2, 3, 255))
    source.save(image_path, format="PNG")
    fake_pm = _FakePM(project_path)
    backend = _FakeImageBackend()

    async def _fake_resolve(*args, **kwargs):
        return _FakeCtx(backend)

    monkeypatch.setattr(canvas_image_tasks, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(canvas_image_tasks, "resolve_generation_context", _fake_resolve)
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    result = await canvas_image_tasks.execute_canvas_image_task(
        "demo",
        "character:Alice",
        {
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "operation": "canvas_image_outpaint",
            "region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
        },
        task_id="task-outpaint",
    )

    output_path = project_path / result["outputs"][0]["file_path"]
    with Image.open(output_path) as output:
        assert output.size == (15, 10)
        assert output.getpixel((2, 1)) == (1, 2, 3, 255)
        assert output.getpixel((7, 5)) == (20, 40, 60, 255)
        assert output.getpixel((0, 0)) == (200, 100, 50, 255)


@pytest.mark.asyncio
async def test_canvas_image_crop_executor_preserves_source_and_returns_media_outputs(tmp_path, monkeypatch):
    project_path = tmp_path / "projects" / "demo"
    image_path = project_path / "characters" / "Alice.png"
    image_path.parent.mkdir(parents=True)
    source = Image.new("RGBA", (12, 8), (20, 40, 60, 255))
    source.save(image_path, format="PNG")
    source_bytes = image_path.read_bytes()
    fake_pm = _FakePM(project_path)
    monkeypatch.setattr(canvas_image_tasks, "get_project_manager", lambda: fake_pm)
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    result = await canvas_image_tasks.execute_canvas_image_task(
        "demo",
        "character:Alice",
        {
            "source_kind": "project",
            "resource_type": "character",
            "resource_id": "Alice",
            "operation": "canvas_image_crop",
            "region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
        },
        task_id="task-crop",
    )

    assert result["operation"] == "canvas_image_crop"
    assert image_path.read_bytes() == source_bytes
    outputs = result["outputs"]
    assert len(outputs) == 1
    assert all(output.get("media_asset_id") for output in outputs)
    with Image.open(project_path / outputs[0]["file_path"]) as cropped:
        # 归一化 region 会落在归一化前的像素区间，这里仅断言已裁出且非空。
        assert cropped.size[0] > 0 and cropped.size[1] > 0
