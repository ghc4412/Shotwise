"""统一解析剧集源文及其派生文件回退。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.episode_ledger import (
    discover_episode_files,
    discover_sources,
    normalize_source_text,
    parse_episode_num,
    parse_source_range,
)
from lib.path_safety import PathTraversalError, safe_join


@dataclass(frozen=True)
class EpisodeSource:
    """解析后的剧集源文及其来源。"""

    path: Path
    relative_path: str
    text: str
    is_derived: bool


def _read_source_file(project_path: Path, relative_path: str) -> tuple[Path, str] | None:
    try:
        path = safe_join(project_path, relative_path)
    except PathTraversalError:
        return None
    if not path.is_file():
        return None
    try:
        return path, normalize_source_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None


def _episode_entry(project: Mapping[str, Any] | None, episode: int) -> Mapping[str, Any] | None:
    if project is None:
        return None
    entries = project.get("episodes")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, Mapping) and parse_episode_num(entry.get("episode")) == episode:
            return entry
    return None


def _ledger_source(project_path: Path, project: Mapping[str, Any] | None, episode: int) -> EpisodeSource | None:
    entry = _episode_entry(project, episode)
    if entry is None:
        return None
    source_range = parse_source_range(entry)
    if source_range is None:
        return None
    relative_path, start, end = source_range
    loaded = _read_source_file(project_path, relative_path)
    if loaded is None:
        return None
    path, text = loaded
    if not 0 <= start <= end <= len(text):
        return None
    episode_text = text[start:end]
    if not episode_text.strip():
        return None
    return EpisodeSource(path=path, relative_path=relative_path, text=episode_text, is_derived=False)


def resolve_episode_source(
    project_path: Path,
    episode: int,
    *,
    source: str | None = None,
    project: Mapping[str, Any] | None = None,
) -> EpisodeSource:
    """按统一优先级解析一集源文。

    显式 ``source`` 始终优先；省略时先使用账本中的原文范围，随后使用原文候选文件，
    随后使用本集手动预拆分的 ``source/episode_N.txt``，最后回退到旧项目的原始源文拼接。
    """
    if source is not None and not isinstance(source, str):
        raise ValueError(f"meta.source 类型非法，须为字符串或 null：{source!r}")
    if source:
        loaded = _read_source_file(project_path, source)
        if loaded is None:
            try:
                safe_join(project_path, source)
            except PathTraversalError as exc:
                raise ValueError(f"路径超出项目目录: {source}") from exc
            raise ValueError(f"未找到源文件: {project_path / source}")
        path, text = loaded
        if not text.strip():
            raise ValueError("小说原文为空")
        return EpisodeSource(path=path, relative_path=source, text=text, is_derived=False)

    ledger_source = _ledger_source(project_path, project, episode)
    if ledger_source is not None:
        return ledger_source

    derived = discover_episode_files(project_path).get(episode)
    if derived is not None:
        text = normalize_source_text(derived.read_text(encoding="utf-8"))
        if text.strip():
            return EpisodeSource(
                path=derived,
                relative_path=derived.relative_to(project_path).as_posix(),
                text=text,
                is_derived=True,
            )

    originals = discover_sources(project_path)
    if originals:
        text = "\n\n".join(doc.text for doc in originals)
        if text.strip():
            return EpisodeSource(
                path=project_path / originals[0].rel_path,
                relative_path=originals[0].rel_path,
                text=text,
                is_derived=False,
            )

    raise ValueError(f"找不到第 {episode} 集源文：请提供 source 文件或准备 source/episode_{episode}.txt")


__all__ = ["EpisodeSource", "resolve_episode_source"]
