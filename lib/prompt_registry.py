"""提示词模板注册表：``agent_runtime_profile`` 的只读元数据投影。

按「流程环节」把随发行版发布的提示词模板分成四组枚举——系统提示词（按内容模式变体）、
subagent 定义、skill 定义、参考文档——供设置页只读浏览。注册表不改写任何模板，也不参与
运行时 prompt 组装：运行时仍由 ``agent_runtime_profile`` 直接加载，这里只是同一批文件的可浏览视图。

分组、内容模式、标题与描述全部从既有文件结构与文件头推导，因此新增模板文件会自动进入
注册表，无需在此登记。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lib.agent_profile import agent_profile_dir

GROUP_SYSTEM = "system"
GROUP_AGENT = "agent"
GROUP_SKILL = "skill"
GROUP_REFERENCE = "reference"

PROMPT_TEMPLATE_GROUPS: tuple[str, ...] = (GROUP_SYSTEM, GROUP_AGENT, GROUP_SKILL, GROUP_REFERENCE)
"""分组顺序；同时是设置页分区浏览的展示顺序。"""

CONTENT_MODES: tuple[str, ...] = ("drama", "narration", "ad")
"""模板可声明的内容模式变体，取值与项目 ``content_mode`` 一致。"""

_FRONTMATTER_KEYS = ("name", "description")
_TITLE_PATTERN = re.compile(r"^#\s+(?P<title>.+?)\s*$")
_SECTION_PATTERN = re.compile(r"^##\s+(?P<section>.+?)\s*$")
_MODE_COMMENT_PATTERN = re.compile(r"<!--\s*mode:\s*(?P<mode>[A-Za-z0-9_-]+)\s*-->")
_MAX_TITLE_CHARS = 200
_MAX_DESCRIPTION_CHARS = 400


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """一条模板的只读元数据；``path`` 是相对 profile 根目录的 POSIX 路径，同时充当标识。"""

    path: str
    group: str
    title: str
    description: str
    content_mode: str | None
    sections: tuple[str, ...]
    char_count: int


@dataclass(frozen=True, slots=True)
class PromptTemplateDetail:
    """模板元数据 + 正文，供详情只读浏览。"""

    template: PromptTemplate
    content: str


def _bounded(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1]}\u2026"


def _frontmatter(text: str) -> dict[str, str]:
    """读取文件头 ``---`` 围栏里的字符串字段；未闭合或字段缺失一律按空表处理。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        key, separator, raw = line.partition(":")
        if not separator:
            continue
        name = key.strip().lower()
        if name in _FRONTMATTER_KEYS:
            values[name] = raw.strip().strip("\"'")
    return {}


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = _TITLE_PATTERN.match(line)
        if match:
            return match.group("title")
    return None


def _sections(text: str) -> tuple[str, ...]:
    sections: list[str] = []
    for line in text.splitlines():
        match = _SECTION_PATTERN.match(line)
        if match:
            sections.append(_bounded(match.group("section"), _MAX_TITLE_CHARS))
    return tuple(sections)


def _first_paragraph(text: str) -> str:
    """取 frontmatter 之后的第一段正文（跳过标题、注释与空行）。"""
    in_frontmatter = False
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if index == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        return stripped
    return ""


def _content_mode(path: Path, text: str) -> str | None:
    """从文件名后缀（``CLAUDE.drama.md``）或文件头 ``<!-- mode: x -->`` 推导内容模式。"""
    for part in reversed(path.name.split(".")):
        if part in CONTENT_MODES:
            return part
    match = _MODE_COMMENT_PATTERN.search(text)
    if match and match.group("mode") in CONTENT_MODES:
        return match.group("mode")
    return None


def _template_candidates(profile_root: Path) -> list[tuple[Path, str]]:
    skills_root = profile_root / ".claude" / "skills"
    candidates: list[tuple[Path, str]] = []
    candidates.extend((path, GROUP_SYSTEM) for path in sorted(profile_root.glob("CLAUDE.*.md")))
    candidates.extend((path, GROUP_AGENT) for path in sorted((profile_root / ".claude" / "agents").glob("*.md")))
    candidates.extend((path, GROUP_SKILL) for path in sorted(skills_root.glob("*/SKILL*.md")))
    candidates.extend(
        (path, GROUP_REFERENCE) for path in sorted((profile_root / ".claude" / "references").glob("*.md"))
    )
    return candidates


def _read_template_text(path: Path) -> str | None:
    """读取模板正文；模板可能带 UTF-8 BOM，按 ``utf-8-sig`` 解码以免标题/围栏误判。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _load_template(profile_root: Path, path: Path, group: str) -> PromptTemplate | None:
    # 只读常规文件：符号链接可能指向 profile 之外，拒绝投影以免元数据越界。
    if path.is_symlink() or not path.is_file():
        return None
    text = _read_template_text(path)
    if text is None:
        return None
    frontmatter = _frontmatter(text)
    relative = path.relative_to(profile_root).as_posix()
    title = _first_heading(text) or frontmatter.get("name") or path.stem
    description = frontmatter.get("description") or _first_paragraph(text)
    return PromptTemplate(
        path=relative,
        group=group,
        title=_bounded(title, _MAX_TITLE_CHARS),
        description=_bounded(description, _MAX_DESCRIPTION_CHARS),
        content_mode=_content_mode(path, text),
        sections=_sections(text),
        char_count=len(text),
    )


def build_prompt_registry(profile_root: Path | None = None) -> list[PromptTemplate]:
    """枚举 profile 下的提示词模板；目录缺失时返回空表而不是报错。"""
    root = profile_root or agent_profile_dir()
    if not root.is_dir():
        return []
    order = {group: index for index, group in enumerate(PROMPT_TEMPLATE_GROUPS)}
    entries: list[PromptTemplate] = []
    for path, group in _template_candidates(root):
        entry = _load_template(root, path, group)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: (order[entry.group], entry.content_mode or "", entry.path))
    return entries


def find_prompt_template(template_id: str, profile_root: Path | None = None) -> PromptTemplateDetail | None:
    """按 ``path`` 读取单条模板的元数据与正文；未知 id 返回 None。

    只按注册表索引查表，不把请求值拼进文件系统路径，因此 ``../`` 之类输入只会命中
    「未知 id」，不会越出 profile 目录。
    """
    root = profile_root or agent_profile_dir()
    for entry in build_prompt_registry(root):
        if entry.path != template_id:
            continue
        content = _read_template_text(root / entry.path)
        if content is None:
            return None
        return PromptTemplateDetail(template=entry, content=content)
    return None


__all__ = [
    "CONTENT_MODES",
    "GROUP_AGENT",
    "GROUP_REFERENCE",
    "GROUP_SKILL",
    "GROUP_SYSTEM",
    "PROMPT_TEMPLATE_GROUPS",
    "PromptTemplate",
    "PromptTemplateDetail",
    "build_prompt_registry",
    "find_prompt_template",
]
