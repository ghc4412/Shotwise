"""Project character relationship graph APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from lib.character_relations import (
    CharacterRelationEdge,
    CharacterRelationPosition,
    apply_manual_relationships,
    empty_character_relations,
    normalize_character_relations,
    relations_payload,
)
from lib.i18n import Translator
from lib.project_change_hints import project_change_source
from lib.project_manager import get_project_manager
from server.services.character_relations import analyze_character_relations

logger = logging.getLogger(__name__)

router = APIRouter()


class SaveCharacterRelationsRequest(BaseModel):
    base_revision: int = Field(ge=0)
    edges: list[CharacterRelationEdge] = Field(default_factory=list, max_length=500)
    node_positions: dict[str, CharacterRelationPosition] | None = Field(default=None, max_length=500)


def _relations_from_project(project: dict[str, Any]) -> dict[str, Any]:
    characters = project.get("characters")
    if not isinstance(characters, dict):
        raise ValueError("project characters must be an object")
    raw = project.get("character_relations")
    relations = normalize_character_relations(raw, characters) if raw is not None else empty_character_relations()
    return relations_payload(relations)


@router.get("/projects/{project_name}/character-relations")
async def get_character_relations(project_name: str, _t: Translator):
    try:
        project = await asyncio.to_thread(get_project_manager().load_project, project_name)
        return _relations_from_project(project)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_t("script_validation_failed", details=str(exc))) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("读取角色关系失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error"))


@router.put("/projects/{project_name}/character-relations")
async def save_character_relations(project_name: str, req: SaveCharacterRelationsRequest, _t: Translator):
    try:

        def _sync() -> dict[str, Any]:
            manager = get_project_manager()
            saved: dict[str, Any] = {}

            def _mutate(project: dict[str, Any]) -> None:
                current = _relations_from_project(project)
                if current["revision"] != req.base_revision:
                    raise RuntimeError("revision_conflict")
                relations = apply_manual_relationships(current, project.get("characters"), req.edges)
                if req.node_positions is not None:
                    positions = normalize_character_relations(
                        {"node_positions": req.node_positions}, project.get("characters")
                    ).node_positions
                    relations = relations.model_copy(update={"node_positions": positions})
                saved.update(relations_payload(relations))
                project["character_relations"] = dict(saved)

            with project_change_source("webui"):
                manager.update_project(project_name, _mutate)
            return saved

        return await asyncio.to_thread(_sync)
    except RuntimeError as exc:
        if str(exc) == "revision_conflict":
            raise HTTPException(status_code=409, detail=_t("character_relations_revision_conflict")) from exc
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_t("script_validation_failed", details=str(exc))) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("保存角色关系失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error"))


@router.post("/projects/{project_name}/character-relations/analyze")
async def analyze_relations(project_name: str, _t: Translator):
    try:
        with project_change_source("webui"):
            return await analyze_character_relations(get_project_manager(), project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=_t("character_relations_analysis_invalid", message=str(exc))
        ) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("AI 角色关系分析失败")
        raise HTTPException(status_code=500, detail=_t("character_relations_analysis_failed"))
