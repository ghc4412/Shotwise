"""``lib.pending_authoring`` 的读时推导测试：三变体的内容投影、id 对齐与三种待编写原因。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib import pending_authoring
from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import script_review as router_mod
from tests.auth_deps import AUTH_DEPENDENCIES


def _make_project(tmp_path: Path, *, content_mode: str = "drama", generation_mode: str | None = None) -> ProjectManager:
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo", content_mode=content_mode)
    pm.create_project_metadata("demo", "Demo", "Anime", content_mode)
    pm.add_episode("demo", 1, "第一集", "scripts/episode_1.json")

    def _mutate(project: dict) -> None:
        project["content_mode"] = content_mode
        if generation_mode is not None:
            project["generation_mode"] = generation_mode

    pm.update_project("demo", _mutate)
    return pm


def _drama_scene(scene_id: str, *, text: str = "你终于回来了。") -> dict:
    """官方剧本里的一个 drama 场景：step1 内容投影 + 视觉层。"""
    return {
        "scene_id": scene_id,
        "duration_seconds": 8,
        "segment_break": False,
        "characters_in_scene": ["阿离"],
        "scenes": [],
        "props": [],
        "utterances": [
            {"kind": "voiceover", "speaker": None, "text": "三年后。"},
            {"kind": "dialogue", "speaker": "阿离", "text": text},
        ],
        "source_text": "三年后，阿离立于屋檐下：你终于回来了。",
        "image_prompt": {"scene": "雨夜屋檐"},
        "video_prompt": {"action": "定格"},
    }


def _drama_step1_scene(scene_id: str, *, text: str = "你终于回来了。") -> dict:
    """step1 里的一个 drama 场景：与官方剧本同源，另带 step1-only 的 scene_description。"""
    scene = _drama_scene(scene_id, text=text)
    scene.pop("image_prompt")
    scene.pop("video_prompt")
    scene["scene_description"] = "雨夜，阿离立于屋檐下"
    return scene


def _write_step1(pm: ProjectManager, payload: dict, filename: str = "step1_normalized_script.json") -> None:
    drafts = pm.get_project_path("demo") / "drafts" / "episode_1"
    drafts.mkdir(parents=True, exist_ok=True)
    atomic_write_json(drafts / filename, payload)


def _write_script(pm: ProjectManager, payload: dict) -> None:
    scripts = pm.get_project_path("demo") / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    atomic_write_json(scripts / "episode_1.json", payload)


def _report(pm: ProjectManager) -> pending_authoring.PendingAuthoringReport:
    return pending_authoring.pending_authoring_report(pm.get_project_path("demo"), pm.load_project("demo"), 1)


class TestApplicability:
    @pytest.mark.unit
    def test_ad_mode_not_applicable(self, tmp_path):
        pm = _make_project(tmp_path, content_mode="ad")
        report = _report(pm)
        assert report.applicable is False
        assert report.kind is None
        assert report.items == ()

    @pytest.mark.unit
    def test_script_absent_reports_nothing_pending(self, tmp_path):
        """「还没生成过剧本」不等于「整集待编写」，不把未产出报成待编写。"""
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        report = _report(pm)
        assert report.applicable is True
        assert report.kind == "drama"
        assert report.script_present is False
        assert report.items == ()
        assert report.has_pending is False

    @pytest.mark.unit
    def test_step1_absent_reports_nothing_pending(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        report = _report(pm)
        assert report.script_present is True
        assert report.items == ()


class TestDramaProjection:
    @pytest.mark.unit
    def test_matching_content_is_clean(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        report = _report(pm)
        assert report.items == ()

    @pytest.mark.unit
    def test_content_change_marks_stale_visual(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01", text="我回来了。")]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01", text="你终于回来了。")]})
        report = _report(pm)
        assert report.item_ids == ("E1S01",)
        assert report.items[0].reason == "stale_visual"

    @pytest.mark.unit
    def test_scene_description_is_ignored(self, tmp_path):
        """scene_description 是 step1-only、合并时被剔除，两侧取值不同不构成待编写。"""
        pm = _make_project(tmp_path)
        step1 = _drama_step1_scene("E1S01")
        step1["scene_description"] = "完全不同的视觉改编描述"
        _write_step1(pm, {"title": "第一集", "scenes": [step1]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        assert _report(pm).items == ()

    @pytest.mark.unit
    def test_script_only_fields_are_ignored(self, tmp_path):
        """note / transition_to_next / generated_assets 是剧本侧 UI / 运行时字段，不参与判定。"""
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        scene = _drama_scene("E1S01")
        scene["note"] = "人工备注"
        scene["transition_to_next"] = "fade"
        scene["generated_assets"] = {"storyboard_image": "a.png"}
        _write_script(pm, {"title": "第一集", "scenes": [scene]})
        assert _report(pm).items == ()

    @pytest.mark.unit
    def test_missing_and_orphan_items(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_step1(
            pm,
            {
                "title": "第一集",
                "scenes": [_drama_step1_scene("E1S01"), _drama_step1_scene("E1S02")],
            },
        )
        _write_script(
            pm,
            {
                "title": "第一集",
                "scenes": [_drama_scene("E1S01"), _drama_scene("E1S99")],
            },
        )
        report = _report(pm)
        assert [(item.item_id, item.reason) for item in report.items] == [
            ("E1S02", "missing_visual"),
            ("E1S99", "orphan_item"),
        ]

    @pytest.mark.unit
    def test_missing_content_field_is_stale(self, tmp_path):
        """剧本缺一个 step1 声明过的字段时判为不一致，不把缺失静默当成通过。"""
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        scene = _drama_scene("E1S01")
        del scene["segment_break"]
        _write_script(pm, {"title": "第一集", "scenes": [scene]})
        report = _report(pm)
        assert report.items[0].reason == "stale_visual"

    @pytest.mark.unit
    def test_malformed_script_lists_degrade_to_empty(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        _write_script(pm, {"title": "第一集", "scenes": "not-a-list"})
        report = _report(pm)
        assert report.script_present is True
        assert report.items == ()

    @pytest.mark.unit
    def test_report_to_dict_shape(self, tmp_path):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01", text="改了")]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        payload = _report(pm).to_dict()
        assert payload == {
            "applicable": True,
            "kind": "drama",
            "script_present": True,
            "has_pending": True,
            "items": [{"item_id": "E1S01", "reason": "stale_visual"}],
        }


class TestNarrationProjection:
    def _narration_step1_segment(self, segment_id: str, *, novel_text: str = "三年后。") -> dict:
        return {
            "segment_id": segment_id,
            "novel_text": novel_text,
            "duration_seconds": 5,
            "segment_break": False,
            "characters_in_segment": ["阿离"],
            "scenes": [],
            "props": [],
        }

    def _narration_segment(self, segment_id: str, *, novel_text: str = "三年后。") -> dict:
        segment = self._narration_step1_segment(segment_id, novel_text=novel_text)
        segment["image_prompt"] = {"scene": "雨夜屋檐"}
        segment["video_prompt"] = {"action": "定格"}
        return segment

    @pytest.mark.unit
    def test_clean_when_novel_text_matches(self, tmp_path):
        pm = _make_project(tmp_path, content_mode="narration")
        _write_step1(
            pm,
            {"segments": [self._narration_step1_segment("E1S01")]},
            filename="step1_segments.json",
        )
        _write_script(pm, {"title": "第一集", "segments": [self._narration_segment("E1S01")]})
        report = _report(pm)
        assert report.kind == "narration"
        assert report.items == ()

    @pytest.mark.unit
    def test_novel_text_change_marks_stale(self, tmp_path):
        pm = _make_project(tmp_path, content_mode="narration")
        _write_step1(
            pm,
            {"segments": [self._narration_step1_segment("E1S01", novel_text="三年后，他回来了。")]},
            filename="step1_segments.json",
        )
        _write_script(pm, {"title": "第一集", "segments": [self._narration_segment("E1S01")]})
        report = _report(pm)
        assert report.items[0].reason == "stale_visual"


class TestReferenceVideoProjection:
    def _rv_step1_unit(self, unit_id: str, *, duration: int = 4) -> dict:
        return {
            "unit_id": unit_id,
            "shots": [{"text": "@[阿离] 立于屋檐下。"}],
            "duration_seconds": duration,
            "references": [{"type": "character", "name": "阿离"}],
            "source_text": "三年后，阿离立于屋檐下。",
        }

    def _rv_unit(self, unit_id: str, *, duration: int = 4) -> dict:
        return {
            "unit_id": unit_id,
            "shots": [{"text": "@[阿离] 全景定格，雨丝掠过屋檐。"}],
            "duration_seconds": duration,
            "references": [{"type": "character", "name": "阿离"}],
        }

    def _project(self, tmp_path: Path) -> ProjectManager:
        return _make_project(tmp_path, content_mode="narration", generation_mode="reference_video")

    @pytest.mark.unit
    def test_shots_text_expansion_is_not_stale(self, tmp_path):
        """shots 正文由 step2 视觉展开改写，两侧必然不同，不构成待编写。"""
        pm = self._project(tmp_path)
        _write_step1(pm, {"units": [self._rv_step1_unit("E1U01")]}, filename="step1_reference_units.json")
        _write_script(pm, {"title": "第一集", "video_units": [self._rv_unit("E1U01")]})
        report = _report(pm)
        assert report.kind == "reference_video"
        assert report.items == ()

    @pytest.mark.unit
    def test_duration_change_marks_stale(self, tmp_path):
        pm = self._project(tmp_path)
        _write_step1(
            pm,
            {"units": [self._rv_step1_unit("E1U01", duration=8)]},
            filename="step1_reference_units.json",
        )
        _write_script(pm, {"title": "第一集", "video_units": [self._rv_unit("E1U01", duration=4)]})
        report = _report(pm)
        assert report.items[0].reason == "stale_visual"

    @pytest.mark.unit
    def test_reference_change_marks_stale(self, tmp_path):
        pm = self._project(tmp_path)
        unit = self._rv_step1_unit("E1U01")
        unit["references"] = [{"type": "character", "name": "阿离"}, {"type": "scene", "name": "屋檐"}]
        _write_step1(pm, {"units": [unit]}, filename="step1_reference_units.json")
        _write_script(pm, {"title": "第一集", "video_units": [self._rv_unit("E1U01")]})
        report = _report(pm)
        assert report.items[0].reason == "stale_visual"

    @pytest.mark.unit
    def test_source_text_is_ignored(self, tmp_path):
        """source_text 是 step1-only，落地时被剔除，两侧取值不同不构成待编写。"""
        pm = self._project(tmp_path)
        unit = self._rv_step1_unit("E1U01")
        unit["source_text"] = "完全不同的原文摘录"
        _write_step1(pm, {"units": [unit]}, filename="step1_reference_units.json")
        _write_script(pm, {"title": "第一集", "video_units": [self._rv_unit("E1U01")]})
        assert _report(pm).items == ()


def _client(monkeypatch, pm: ProjectManager) -> TestClient:
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: pm)
    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(router_mod.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app)


class TestPendingAuthoringRouter:
    @pytest.mark.unit
    def test_reports_stale_items(self, tmp_path, monkeypatch):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01", text="改了")]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        client = _client(monkeypatch, pm)
        with client:
            got = client.get("/api/v1/projects/demo/episodes/1/pending-authoring")
        assert got.status_code == 200
        assert got.json() == {
            "applicable": True,
            "kind": "drama",
            "script_present": True,
            "has_pending": True,
            "items": [{"item_id": "E1S01", "reason": "stale_visual"}],
        }

    @pytest.mark.unit
    def test_clean_episode_reports_no_items(self, tmp_path, monkeypatch):
        pm = _make_project(tmp_path)
        _write_step1(pm, {"title": "第一集", "scenes": [_drama_step1_scene("E1S01")]})
        _write_script(pm, {"title": "第一集", "scenes": [_drama_scene("E1S01")]})
        client = _client(monkeypatch, pm)
        with client:
            got = client.get("/api/v1/projects/demo/episodes/1/pending-authoring")
        assert got.status_code == 200
        assert got.json()["items"] == []
        assert got.json()["has_pending"] is False

    @pytest.mark.unit
    def test_unknown_project_is_404(self, tmp_path, monkeypatch):
        pm = _make_project(tmp_path)
        client = _client(monkeypatch, pm)
        with client:
            got = client.get("/api/v1/projects/missing/episodes/1/pending-authoring")
        assert got.status_code == 404
