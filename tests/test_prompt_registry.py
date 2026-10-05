"""提示词模板注册表：扫描/元数据推导 + 只读 API。"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.prompt_registry import (
    GROUP_AGENT,
    GROUP_REFERENCE,
    GROUP_SKILL,
    GROUP_SYSTEM,
    build_prompt_registry,
    find_prompt_template,
)
from server.error_handlers import register_error_handlers
from server.routers import prompt_registry
from tests.auth_deps import AUTH_DEPENDENCIES, override_auth

pytestmark = pytest.mark.unit

REPO_PROFILE = Path(__file__).resolve().parent.parent / "agent_runtime_profile"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture()
def fake_profile(tmp_path: Path) -> Path:
    """构造一棵覆盖四个分组的假 profile；系统提示词故意带 BOM。"""
    root = tmp_path / "profile"
    _write(
        root / "CLAUDE.drama.md",
        "\ufeff# \u7cfb\u7edf\u63d0\u793a\u8bcd\n\n<!-- mode: drama -->\n\n## \u603b\u5219\n\u6b63\u6587\n\n## \u5de5\u5177\n\u66f4\u591a\n",
    )
    _write(
        root / ".claude" / "agents" / "alpha.md",
        '---\nname: alpha\ndescription: "\u4ee3\u7406\u8bf4\u660e"\n---\n\n# Alpha Agent\n\n## \u6b65\u9aa4\n',
    )
    _write(root / ".claude" / "skills" / "beta" / "SKILL.md", "# \u6280\u80fd\u6807\u9898\n\n## \u89c4\u5219\n")
    _write(root / ".claude" / "skills" / "beta" / "SKILL.ad.md", "# \u5e7f\u544a\u53d8\u4f53\n")
    _write(root / ".claude" / "references" / "modes.md", "# \u53c2\u8003\n")
    return root


class TestBuildPromptRegistry:
    def test_entries_follow_group_then_mode_then_path_order(self, fake_profile: Path):
        entries = build_prompt_registry(fake_profile)

        assert [entry.group for entry in entries] == [
            GROUP_SYSTEM,
            GROUP_AGENT,
            GROUP_SKILL,
            GROUP_SKILL,
            GROUP_REFERENCE,
        ]
        assert [entry.path for entry in entries if entry.group == GROUP_SKILL] == [
            ".claude/skills/beta/SKILL.md",
            ".claude/skills/beta/SKILL.ad.md",
        ]

    def test_metadata_is_derived_from_file_structure(self, fake_profile: Path):
        entries = {entry.path: entry for entry in build_prompt_registry(fake_profile)}

        system = entries["CLAUDE.drama.md"]
        assert system.title == "\u7cfb\u7edf\u63d0\u793a\u8bcd"
        assert system.content_mode == "drama"
        assert system.sections == ("\u603b\u5219", "\u5de5\u5177")
        assert system.char_count > 0

        agent = entries[".claude/agents/alpha.md"]
        assert agent.title == "Alpha Agent"
        assert agent.description == "\u4ee3\u7406\u8bf4\u660e"
        assert agent.content_mode is None

        assert entries[".claude/skills/beta/SKILL.ad.md"].content_mode == "ad"
        assert entries[".claude/skills/beta/SKILL.md"].content_mode is None

    def test_missing_profile_directory_returns_empty(self, tmp_path: Path):
        assert build_prompt_registry(tmp_path / "absent") == []

    def test_symlinked_template_is_not_indexed(self, fake_profile: Path):
        target = fake_profile.parent / "outside.md"
        _write(target, "# outside\n")
        link = fake_profile / ".claude" / "references" / "leak.md"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")

        paths = {entry.path for entry in build_prompt_registry(fake_profile)}
        assert ".claude/references/leak.md" not in paths
        assert ".claude/references/modes.md" in paths


class TestFindPromptTemplate:
    def test_returns_metadata_and_content(self, fake_profile: Path):
        detail = find_prompt_template("CLAUDE.drama.md", fake_profile)

        assert detail is not None
        assert detail.template.group == GROUP_SYSTEM
        assert "## \u603b\u5219" in detail.content

    @pytest.mark.parametrize(
        "candidate",
        ["", "../.env", "..\\..\\.env", ".claude/agents/nope.md", "CLAUDE.md"],
    )
    def test_unknown_or_traversing_ids_return_none(self, fake_profile: Path, candidate: str):
        assert find_prompt_template(candidate, fake_profile) is None


class TestShippedProfile:
    def test_repo_profile_indexes_every_group(self):
        entries = build_prompt_registry(REPO_PROFILE)

        assert {entry.group for entry in entries} == {GROUP_SYSTEM, GROUP_AGENT, GROUP_SKILL, GROUP_REFERENCE}
        assert {entry.content_mode for entry in entries if entry.group == GROUP_SYSTEM} == {
            "ad",
            "drama",
            "narration",
        }
        assert all(entry.title and entry.char_count > 0 for entry in entries)


class TestPromptRegistryApi:
    @pytest.fixture()
    def app(self, fake_profile: Path) -> FastAPI:
        _app = FastAPI()
        override_auth(_app)
        _app.include_router(prompt_registry.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
        register_error_handlers(_app)
        return _app

    @pytest.fixture()
    def client(
        self, app: FastAPI, fake_profile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Generator[TestClient, None, None]:
        monkeypatch.setenv("SHOTWISE_PROFILE_DIR", str(fake_profile))
        with TestClient(app) as test_client:
            yield test_client

    def test_list_returns_metadata_without_content(self, client: TestClient):
        response = client.get("/api/v1/prompts/registry")

        assert response.status_code == 200
        templates = response.json()["templates"]
        assert [item["path"] for item in templates] == [
            "CLAUDE.drama.md",
            ".claude/agents/alpha.md",
            ".claude/skills/beta/SKILL.md",
            ".claude/skills/beta/SKILL.ad.md",
            ".claude/references/modes.md",
        ]
        assert templates[0]["sections"] == ["\u603b\u5219", "\u5de5\u5177"]
        assert "content" not in templates[0]

    def test_detail_returns_content_for_nested_path(self, client: TestClient):
        response = client.get("/api/v1/prompts/registry/.claude/skills/beta/SKILL.md")

        assert response.status_code == 200
        body = response.json()
        assert body["template"]["group"] == GROUP_SKILL
        assert body["content"].startswith("# ")

    def test_unknown_path_returns_404(self, client: TestClient):
        response = client.get("/api/v1/prompts/registry/.claude/agents/nope.md")

        assert response.status_code == 404
        assert response.json()["detail"]

    def test_requires_authentication(self) -> None:
        _app = FastAPI()
        _app.include_router(prompt_registry.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
        register_error_handlers(_app)

        with TestClient(_app) as unauthenticated:
            assert unauthenticated.get("/api/v1/prompts/registry").status_code == 401
