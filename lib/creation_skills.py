"""Official, versioned catalog for user-facing creation Skills.

Creation Skills are product capabilities. They are not Agent Skills from
agent_runtime_profile/.claude/skills, and the first release has no user
authoring, publishing, or marketplace interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

CreationScope = Literal["project", "episode", "selection"]


@dataclass(frozen=True)
class CreationSkillCompatibility:
    """The Project modes and selected inputs a creation Skill accepts."""

    content_modes: frozenset[str]
    generation_modes: frozenset[str]
    required_inputs: frozenset[str] = frozenset()
    scopes: frozenset[CreationScope] = frozenset({"project"})
    grid_storyboards: frozenset[bool] | None = None

    def check(self, project: Mapping[str, object], available_inputs: set[str]) -> str | None:
        if project.get("content_mode") not in self.content_modes:
            return "content_mode_incompatible"
        if project.get("generation_mode") not in self.generation_modes:
            return "generation_mode_incompatible"
        if self.grid_storyboards is not None and bool(project.get("grid_storyboard")) not in self.grid_storyboards:
            return "grid_storyboard_incompatible"
        if missing := self.required_inputs - available_inputs:
            return f"missing_inputs:{','.join(sorted(missing))}"
        return None

    def explain(self, project: Mapping[str, object], available_inputs: set[str]) -> dict[str, object]:
        """Return a stable, non-content-bearing compatibility result for the UI and analytics."""

        content_mode = project.get("content_mode")
        generation_mode = project.get("generation_mode")
        missing = sorted(self.required_inputs - available_inputs)
        reasons: list[str] = []
        if content_mode not in self.content_modes:
            reasons.append("content_mode_incompatible")
        if generation_mode not in self.generation_modes:
            reasons.append("generation_mode_incompatible")
        if self.grid_storyboards is not None and bool(project.get("grid_storyboard")) not in self.grid_storyboards:
            reasons.append("grid_storyboard_incompatible")
        if missing:
            reasons.append(f"missing_inputs:{','.join(missing)}")
        return {
            "compatible": not reasons,
            "project_content_mode": content_mode,
            "project_generation_mode": generation_mode,
            "supported_content_modes": sorted(self.content_modes),
            "supported_generation_modes": sorted(self.generation_modes),
            "grid_storyboard": project.get("grid_storyboard"),
            "supported_grid_storyboards": sorted(self.grid_storyboards) if self.grid_storyboards is not None else None,
            "reasons": reasons,
            "requires_new_project": "generation_mode_incompatible" in reasons,
        }


@dataclass(frozen=True)
class CreationSkillVersion:
    """Immutable official release pinned to a published-template alias."""

    id: str
    skill_id: str
    version: int
    title: str
    summary: str
    category: str
    workflow_template_revision_alias: str
    compatibility: CreationSkillCompatibility
    expected_outputs: tuple[str, ...]
    review_required: bool = False
    estimated_cost_hint: str | None = None
    workflow_revision_id: str | None = None


@dataclass(frozen=True)
class CreationSkillDefinition:
    """Stable public identity for one official product capability."""

    id: str
    slug: str
    latest_version: CreationSkillVersion
    official: Literal[True] = True
    active: bool = True


def compatibility_report(
    skill: CreationSkillDefinition,
    project: Mapping[str, object],
    available_inputs: set[str],
    *,
    alternatives: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build the structured incompatibility response without exposing user content."""

    result = skill.latest_version.compatibility.explain(project, available_inputs)
    reasons = result.get("reasons")
    result.update(
        {
            "skill_id": skill.id,
            "skill_version_id": skill.latest_version.id,
            "alternative_skills": list(alternatives),
            "conflict_reason": reasons[0] if isinstance(reasons, list) and reasons else None,
        }
    )
    return result


def _skill(
    skill_id: str,
    title: str,
    summary: str,
    category: str,
    *,
    content_modes: set[str],
    generation_modes: set[str],
    required_inputs: set[str],
    scopes: set[CreationScope],
    outputs: tuple[str, ...],
    review_required: bool = False,
    grid_storyboards: set[bool] | None = None,
    workflow_revision_id: str | None = None,
) -> CreationSkillDefinition:
    version = CreationSkillVersion(
        id=f"{skill_id}:v1",
        skill_id=skill_id,
        version=1,
        title=title,
        summary=summary,
        category=category,
        workflow_template_revision_alias=f"official:{skill_id}",
        compatibility=CreationSkillCompatibility(
            content_modes=frozenset(content_modes),
            generation_modes=frozenset(generation_modes),
            required_inputs=frozenset(required_inputs),
            scopes=frozenset(scopes),
            grid_storyboards=frozenset(grid_storyboards) if grid_storyboards is not None else None,
        ),
        expected_outputs=outputs,
        review_required=review_required,
        workflow_revision_id=workflow_revision_id,
    )
    return CreationSkillDefinition(id=skill_id, slug=skill_id, latest_version=version)


OFFICIAL_CREATION_SKILLS: tuple[CreationSkillDefinition, ...] = (
    _skill(
        "novel-to-drama",
        "小说转连续短剧",
        "将文稿编排为角色、场景、分镜和剧集视频。",
        "剧集",
        content_modes={"drama"},
        generation_modes={"storyboard"},
        required_inputs={"document"},
        scopes={"project"},
        outputs=("script", "characters", "scenes", "storyboards", "videos"),
    ),
    _skill(
        "novel-to-narration",
        "小说转旁白解说",
        "将文稿整理为旁白驱动的视频剧集。",
        "解说",
        content_modes={"narration"},
        generation_modes={"storyboard"},
        required_inputs={"document"},
        scopes={"project"},
        outputs=("script", "storyboards", "narration", "videos"),
    ),
    _skill(
        "ad-brief-to-video",
        "广告 Brief 转分镜视频",
        "根据 Brief 与商品素材生成广告镜头。",
        "广告",
        content_modes={"ad"},
        generation_modes={"storyboard"},
        required_inputs={"brief"},
        scopes={"project"},
        outputs=("shots", "storyboards", "videos"),
    ),
    _skill(
        "reference-image-video",
        "参考图生成视频",
        "使用项目资产图作为参考生成视频单元。",
        "视频",
        content_modes={"drama", "narration", "ad"},
        generation_modes={"reference_video"},
        required_inputs={"image"},
        scopes={"episode", "selection"},
        outputs=("videos",),
    ),
    _skill(
        "grid-storyboard-batch",
        "宫格分镜批量生成",
        "按项目宫格策略批量生成分镜。",
        "分镜",
        content_modes={"drama", "narration"},
        generation_modes={"storyboard"},
        required_inputs={"document"},
        scopes={"episode"},
        outputs=("storyboards",),
        grid_storyboards={True},
    ),
    _skill(
        "character-consistency",
        "角色定妆与一致性测试",
        "生成角色定妆图和一致性参考。",
        "角色",
        content_modes={"drama", "narration", "ad"},
        generation_modes={"storyboard", "reference_video"},
        required_inputs={"image"},
        scopes={"selection"},
        outputs=("images",),
        review_required=True,
    ),
    _skill(
        "redraw-storyboard",
        "选中分镜重绘",
        "按选中的分镜和参考重绘画面。",
        "分镜",
        content_modes={"drama", "narration", "ad"},
        generation_modes={"storyboard"},
        required_inputs={"image"},
        scopes={"selection"},
        outputs=("storyboards",),
    ),
    _skill(
        "redub-video",
        "选中视频重新配音",
        "为选中的视频重新生成旁白或对白音轨。",
        "音频",
        content_modes={"drama", "narration", "ad"},
        generation_modes={"storyboard", "reference_video"},
        required_inputs={"video"},
        scopes={"selection"},
        outputs=("audio", "videos"),
    ),
)


def list_official_creation_skills(
    project: Mapping[str, object], available_inputs: set[str]
) -> list[tuple[CreationSkillDefinition, str | None]]:
    """List active official Skills and their compatibility result."""

    return [
        (skill, skill.latest_version.compatibility.check(project, available_inputs))
        for skill in OFFICIAL_CREATION_SKILLS
        if skill.active
    ]
