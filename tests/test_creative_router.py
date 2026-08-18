from types import SimpleNamespace

import pytest

from server.routers import creative

pytestmark = pytest.mark.unit


def test_build_creative_draft_prompt_respects_screenplay_semantics() -> None:
    prompt = creative.build_creative_draft_prompt(
        operation="rewrite",
        content_mode="drama",
        source_kind="screenplay",
        content="甲：我们得走了。",
        instruction="让冲突更强",
    )

    assert "不得无故丢失台词" in prompt
    assert "让冲突更强" in prompt
    assert "甲：我们得走了。" in prompt


def test_build_creative_draft_prompt_supports_expanding_existing_draft() -> None:
    prompt = creative.build_creative_draft_prompt(
        operation="expand",
        content_mode="drama",
        source_kind="novel",
        content="林舟推开旧仓库的门。",
        instruction="加强雨夜氛围",
    )

    assert "扩写草稿" in prompt
    assert "林舟推开旧仓库的门。" in prompt


@pytest.mark.asyncio
async def test_generate_creative_draft_returns_text_without_persisting(monkeypatch) -> None:
    class ProjectManager:
        def load_project(self, project_name: str):
            assert project_name == "demo"
            return {"content_mode": "narration"}

    class Generator:
        async def generate(self, request, project_name: str):
            assert project_name == "demo"
            assert "一句话" in request.prompt
            return SimpleNamespace(text="生成的旁白稿", provider="test", model="text-model")

    async def create_generator(*_args, **_kwargs):
        return Generator()

    monkeypatch.setattr(creative, "get_project_manager", lambda: ProjectManager())
    monkeypatch.setattr(creative.TextGenerator, "create", create_generator)

    result = await creative.generate_creative_draft(
        "demo",
        creative.CreativeDraftRequest(operation="generate", instruction="一句话：雨夜里的旧车站"),
        lambda key, **_kwargs: key,
    )

    assert result == {
        "operation": "generate",
        "content": "生成的旁白稿",
        "provider": "test",
        "model": "text-model",
    }
