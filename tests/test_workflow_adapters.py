"""Adapter tests: registry coverage and pure wiring-node behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.services import workflow_adapters
from server.services.workflow_adapters import NodeFailedError
from server.services.workflow_execution import AssetRef, NodeContext

pytestmark = pytest.mark.unit

EXPECTED_NODE_TYPES = {
    # existing business nodes
    "character_reference",
    "compose",
    "export",
    "quality_check",
    "script_generate",
    "script_review",
    # production chain nodes
    "source_import",
    "storyboard_generate",
    "storyboard_review",
    "shot_image_generate",
    "shot_video_generate",
    "voice_generate",
    # generic nodes
    "image_input",
    "video_input",
    "loop",
    "branch",
    "param_adjust",
}


def _ctx(tmp_path: Path, node_type: str, config: dict[str, Any], upstream: dict | None = None) -> NodeContext:
    logs: list[tuple[str, str]] = []

    def log(level: str, line: str) -> None:
        logs.append((level, line))

    return NodeContext(
        project_name="demo",
        project_path=tmp_path,
        node_key="node",
        node_type=node_type,
        config=config,
        upstream_outputs=upstream or {},
        log=log,
        progress=lambda _value: None,
        cancelled=lambda: _never(),
    )


async def _run(tmp_path: Path, node_type: str, config: dict[str, Any], upstream: dict | None = None):
    adapter = workflow_adapters.get_adapter(node_type)
    assert adapter is not None
    return await adapter(_ctx(tmp_path, node_type, config, upstream))


async def _never() -> bool:
    return False


def test_registry_covers_expected_node_types() -> None:
    assert EXPECTED_NODE_TYPES <= set(workflow_adapters.REGISTRY)


@pytest.mark.parametrize("node_type", sorted(EXPECTED_NODE_TYPES))
async def test_all_registered_adapters_are_async_functions(tmp_path: Path, node_type: str) -> None:
    adapter = workflow_adapters.get_adapter(node_type)
    assert adapter is not None
    import inspect

    assert inspect.iscoroutinefunction(adapter)


async def test_branch_selects_true_port(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "branch", {"condition": {"field": "mode", "equals": "auto"}, "mode": "auto"})
    result = await _run(tmp_path, "branch", ctx.config)
    assert "true" in result.outputs
    assert "false" not in result.outputs


async def test_branch_selects_false_port(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "branch", {"condition": {"field": "mode", "equals": "auto"}, "mode": "manual"})
    result = await _run(tmp_path, "branch", ctx.config)
    assert "false" in result.outputs
    assert "true" not in result.outputs


async def test_param_adjust_emits_overrides(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "param_adjust", {"overrides": {"resolution": "1080p", "duration": 8}})
    result = await _run(tmp_path, "param_adjust", ctx.config)
    assert result.outputs["params"][0].kind == "params"


async def test_loop_counts_items_from_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "loop", {"items": ["a", "b", "c"]})
    result = await _run(tmp_path, "loop", ctx.config)
    assert result.outputs["items"][0].count == 3


async def test_loop_falls_back_to_upstream_labels(tmp_path: Path) -> None:
    upstream = {
        "upstream_node": {"out": [AssetRef(kind="image", label="shot-1"), AssetRef(kind="image", label="shot-2")]}
    }
    result = await _run(tmp_path, "loop", {}, upstream)
    assert result.outputs["items"][0].count == 2


async def test_image_input_requires_existing_path(tmp_path: Path) -> None:
    with pytest.raises(NodeFailedError, match="图片不存在"):
        await _run(tmp_path, "image_input", {"path": "refs/missing.png"})


async def test_image_input_ok(tmp_path: Path) -> None:
    ref_dir = tmp_path / "refs"
    ref_dir.mkdir()
    (ref_dir / "hero.png").write_text("png", encoding="utf-8")
    result = await _run(tmp_path, "image_input", {"path": "refs/hero.png", "label": "hero"})
    assert result.outputs["image"][0].path == "refs/hero.png"


async def test_source_import_ok(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "novel.txt").write_text("content", encoding="utf-8")
    result = await _run(tmp_path, "source_import", {"source_file": "source/novel.txt"})
    assert result.outputs["source"][0].path == "source/novel.txt"


async def test_quality_check_reports_missing_artifacts(tmp_path: Path) -> None:
    upstream = {"shot": {"video": [AssetRef(kind="video", path="videos/missing.mp4")]}}
    with pytest.raises(NodeFailedError, match="产物缺失"):
        await _run(tmp_path, "quality_check", {}, upstream)
