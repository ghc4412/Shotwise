"""Tests for the canonical episode source resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.episode_source import resolve_episode_source

pytestmark = pytest.mark.unit


def test_ledger_source_range_is_used_before_other_source_candidates(tmp_path: Path) -> None:
    source = tmp_path / "source" / "novel.txt"
    source.parent.mkdir()
    source.write_bytes("前文\r\n\r\n第二集内容".encode())
    (source.parent / "episode_2.txt").write_text("错误的回退内容", encoding="utf-8")

    resolved = resolve_episode_source(
        tmp_path,
        2,
        project={
            "episodes": [{"episode": 2, "source_range": {"source_file": "source/novel.txt", "start": 4, "end": 9}}]
        },
    )

    assert resolved.relative_path == "source/novel.txt"
    assert resolved.text == "第二集内容"
    assert resolved.is_derived is False


def test_derived_episode_file_is_preferred_for_omitted_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "novel.txt").write_text("整本原文", encoding="utf-8")
    derived = source_dir / "episode_1.txt"
    derived.write_text("本集派生内容", encoding="utf-8")

    resolved = resolve_episode_source(tmp_path, 1, project={"episodes": []})

    assert resolved.path == derived
    assert resolved.text == "本集派生内容"
    assert resolved.is_derived is True


def test_derived_episode_file_is_source_when_original_source_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "source" / "episode_01.txt"
    path.parent.mkdir()
    path.write_bytes("第一集\r\n内容".encode())

    resolved = resolve_episode_source(tmp_path, 1, project={"episodes": []})

    assert resolved.path == path
    assert resolved.relative_path == "source/episode_01.txt"
    assert resolved.text == "第一集\n内容"
    assert resolved.is_derived is True


def test_explicit_source_has_priority_and_normalizes_text(tmp_path: Path) -> None:
    source = tmp_path / "source" / "chosen.txt"
    source.parent.mkdir()
    source.write_bytes("Café\r\n正文".encode())
    (source.parent / "episode_1.txt").write_text("派生文件", encoding="utf-8")

    resolved = resolve_episode_source(
        tmp_path,
        1,
        source="source/chosen.txt",
        project={
            "episodes": [{"episode": 1, "source_range": {"source_file": "source/chosen.txt", "start": 0, "end": 7}}]
        },
    )

    assert resolved.text == "Café\n正文"
    assert resolved.relative_path == "source/chosen.txt"
    assert resolved.is_derived is False


def test_episode_source_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="路径超出项目目录"):
        resolve_episode_source(tmp_path, 1, source="../outside.txt")


def test_missing_episode_source_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"找不到第 3 集源文"):
        resolve_episode_source(tmp_path, 3, project={"episodes": []})


def test_empty_explicit_source_is_treated_as_omitted(tmp_path: Path) -> None:
    path = tmp_path / "source" / "episode_1.txt"
    path.parent.mkdir()
    path.write_text("可用内容", encoding="utf-8")

    resolved = resolve_episode_source(tmp_path, 1, source="", project={"episodes": []})

    assert resolved.path == path
    assert resolved.is_derived is True
