"""Creative-draft text generation for the project source workspace."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lib.api_errors import BadRequestError, NotFoundError
from lib.i18n import Translator
from lib.project_manager import get_project_manager
from lib.text_backends.base import DEFAULT_MAX_OUTPUT_TOKENS, TextGenerationRequest, TextTaskType
from lib.text_generator import TextGenerator

logger = logging.getLogger(__name__)

router = APIRouter()

CreativeOperation = Literal["generate", "continue", "rewrite", "polish", "outline", "split"]


class CreativeDraftRequest(BaseModel):
    """One explicit text operation against the unsaved draft in the browser."""

    operation: CreativeOperation
    content: str = Field(default="", max_length=120_000)
    instruction: str = Field(default="", max_length=4_000)


def _mode_instruction(content_mode: str, source_kind: str) -> str:
    if content_mode == "narration":
        return "这是短视频旁白项目。输出应是自然、可口播的叙事文本，画面信息只在确有帮助时简洁提示。"
    if source_kind == "screenplay":
        return "这是剧集剧本项目。保持场次、角色、对白和旁白清晰；修改既有文本时不得无故丢失台词。"
    return "这是小说改编的剧集项目。输出故事正文，保持人物动机、冲突和场景推进可供后续分集与改编使用。"


def _operation_instruction(operation: CreativeOperation) -> str:
    return {
        "generate": "根据创作要求写出一个可继续编辑的完整初稿。",
        "continue": "在不重复已有内容的前提下续写下一段，延续人物、语气和叙事线索。",
        "rewrite": "按创作要求重写这份草稿，保留没有被要求改变的核心事实。",
        "polish": "润色这份草稿，使表达更清楚、有节奏，避免改变剧情事实。",
        "outline": "输出层级清晰的故事大纲，不要重写正文。",
        "split": "把草稿拆成可供后续分集规划的章节或场景列表，并为每项给出简短摘要。",
    }[operation]


def build_creative_draft_prompt(
    *,
    operation: CreativeOperation,
    content_mode: str,
    source_kind: str,
    content: str,
    instruction: str,
) -> str:
    """Build a mode-aware free-text request without making it a production script."""

    parts = [
        "你是项目创作稿编辑器中的写作助手。",
        _mode_instruction(content_mode, source_kind),
        _operation_instruction(operation),
        "只输出用户可直接阅读和编辑的内容；不要输出解释、JSON、代码块或自我说明。",
    ]
    if instruction.strip():
        parts.extend(["# 创作要求", instruction.strip()])
    if content.strip():
        parts.extend(["# 当前创作稿", "<draft>", content.strip(), "</draft>"])
    return "\n\n".join(parts)


@router.post("/projects/{project_name}/creative-draft/generate")
async def generate_creative_draft(project_name: str, req: CreativeDraftRequest, _t: Translator):
    """Generate a draft suggestion; persistence remains an explicit browser action."""

    try:
        project = get_project_manager().load_project(project_name)
    except FileNotFoundError as exc:
        raise NotFoundError("project_not_found", name=project_name) from exc

    content_mode = str(project.get("content_mode") or "narration")
    if content_mode == "ad":
        raise BadRequestError("request_invalid")

    instruction = req.instruction.strip()
    content = req.content.strip()
    if req.operation == "generate" and not instruction:
        raise BadRequestError("request_invalid")
    if req.operation != "generate" and not content:
        raise BadRequestError("request_invalid")

    try:
        generator = await TextGenerator.create(TextTaskType.SCRIPT, project_name=project_name)
        result = await generator.generate(
            TextGenerationRequest(
                prompt=build_creative_draft_prompt(
                    operation=req.operation,
                    content_mode=content_mode,
                    source_kind=str(project.get("source_kind") or "novel"),
                    content=content,
                    instruction=instruction,
                ),
                max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            ),
            project_name=project_name,
        )
        return {
            "operation": req.operation,
            "content": result.text.strip(),
            "provider": result.provider,
            "model": result.model,
        }
    except BadRequestError:
        raise
    except ValueError as exc:
        logger.warning("创作稿生成请求无效 project=%s: %s", project_name, exc)
        raise BadRequestError("request_invalid") from exc
    except Exception:
        logger.exception("创作稿生成失败 project=%s", project_name)
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from None
