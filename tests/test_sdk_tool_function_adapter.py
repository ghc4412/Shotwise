from types import SimpleNamespace
from typing import Any

import pytest

from server.agent_runtime.sdk_tools import _sdk_tool_to_function_tool

pytestmark = pytest.mark.unit


class _RecordingHandler:
    def __init__(self) -> None:
        self.args: dict[str, Any] | None = None

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        self.args = args
        return {"content": [{"type": "text", "text": "ok"}]}


def _make_function_tool(handler: _RecordingHandler) -> Any:
    return _sdk_tool_to_function_tool(
        SimpleNamespace(
            name="fake_tool",
            description="fake tool",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
        )
    )


@pytest.mark.asyncio
async def test_function_tool_accepts_mapping_params_without_json_loads_error() -> None:
    handler = _RecordingHandler()
    function_tool = _make_function_tool(handler)

    result = await function_tool.on_invoke_tool(None, {"value": 1})

    assert result == "ok"
    assert handler.args == {"value": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [None, "", "not-json", '["not", "an", "object"]', 42])
async def test_function_tool_degrades_non_object_params_to_empty_args(params: Any) -> None:
    handler = _RecordingHandler()
    function_tool = _make_function_tool(handler)

    result = await function_tool.on_invoke_tool(None, params)

    assert result == "ok"
    assert handler.args == {}


@pytest.mark.asyncio
async def test_function_tool_decodes_json_object_params() -> None:
    handler = _RecordingHandler()
    function_tool = _make_function_tool(handler)

    result = await function_tool.on_invoke_tool(None, '{"value": 1}')

    assert result == "ok"
    assert handler.args == {"value": 1}
