from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.project_list_cache import ProjectListReadCache


class _JsonProjectManager:
    def __init__(self, root: Path):
        self.projects_root = root
        self.project_loads = 0
        self.script_loads = 0

    @staticmethod
    def normalize_script_filename(filename: str) -> str:
        return filename.removeprefix("scripts/")

    def load_project(self, name: str) -> dict:
        self.project_loads += 1
        path = self.projects_root / name / "project.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def load_script(self, name: str, filename: str) -> dict:
        self.script_loads += 1
        path = self.projects_root / name / "scripts" / self.normalize_script_filename(filename)
        if not path.is_file():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.mark.unit
def test_project_list_cache_reuses_unchanged_json_and_isolates_callers(tmp_path):
    _write_json(tmp_path / "demo" / "project.json", {"title": "原始标题"})
    manager = _JsonProjectManager(tmp_path)
    cache = ProjectListReadCache()

    first = cache.load_project(manager, "demo")
    first["title"] = "调用方修改"
    second = cache.load_project(manager, "demo")

    assert second == {"title": "原始标题"}
    assert manager.project_loads == 1


@pytest.mark.unit
def test_project_list_cache_reads_external_project_change_on_next_request(tmp_path):
    project_file = tmp_path / "demo" / "project.json"
    _write_json(project_file, {"title": "旧标题"})
    manager = _JsonProjectManager(tmp_path)
    cache = ProjectListReadCache()

    assert cache.load_project(manager, "demo")["title"] == "旧标题"
    _write_json(project_file, {"title": "新标题"})

    assert cache.load_project(manager, "demo")["title"] == "新标题"
    assert manager.project_loads == 2


@pytest.mark.unit
def test_project_list_cache_reads_external_script_change_on_next_request(tmp_path):
    script_file = tmp_path / "demo" / "scripts" / "episode_1.json"
    _write_json(script_file, {"title": "旧剧本"})
    manager = _JsonProjectManager(tmp_path)
    cache = ProjectListReadCache()

    assert cache.load_script(manager, "demo", "scripts/episode_1.json")["title"] == "旧剧本"
    _write_json(script_file, {"title": "新剧本"})

    assert cache.load_script(manager, "demo", "scripts/episode_1.json")["title"] == "新剧本"
    assert manager.script_loads == 2


@pytest.mark.unit
def test_project_list_cache_does_not_return_deleted_source(tmp_path):
    project_file = tmp_path / "demo" / "project.json"
    _write_json(project_file, {"title": "项目"})
    manager = _JsonProjectManager(tmp_path)
    cache = ProjectListReadCache()

    assert cache.load_project(manager, "demo")["title"] == "项目"
    project_file.unlink()

    with pytest.raises(FileNotFoundError):
        cache.load_project(manager, "demo")
    assert manager.project_loads == 2


@pytest.mark.unit
def test_project_list_cache_scales_one_read_per_distinct_json_input(tmp_path):
    project_count = 4
    episode_count = 5
    for project_index in range(project_count):
        name = f"project-{project_index}"
        _write_json(tmp_path / name / "project.json", {"title": name})
        for episode_index in range(episode_count):
            _write_json(
                tmp_path / name / "scripts" / f"episode_{episode_index}.json",
                {"episode": episode_index, "title": f"{name}-{episode_index}"},
            )

    manager = _JsonProjectManager(tmp_path)
    cache = ProjectListReadCache()

    for _ in range(2):
        for project_index in range(project_count):
            name = f"project-{project_index}"
            cache.load_project(manager, name)
            for episode_index in range(episode_count):
                cache.load_script(manager, name, f"scripts/episode_{episode_index}.json")

    assert manager.project_loads == project_count
    assert manager.script_loads == project_count * episode_count

    changed_script = tmp_path / "project-2" / "scripts" / "episode_3.json"
    _write_json(changed_script, {"episode": 3, "title": "changed-content"})
    cache.load_script(manager, "project-2", "scripts/episode_3.json")

    assert manager.project_loads == project_count
    assert manager.script_loads == project_count * episode_count + 1
