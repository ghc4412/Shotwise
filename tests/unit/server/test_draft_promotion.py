from __future__ import annotations

from typing import Any, cast

import pytest

from server.draft_promotion import (
    DraftPromotionService,
    DraftTarget,
    DraftValidationIssue,
    OfficialRevisionConflict,
    PromotionConflict,
)


class MemoryDraftPromotionRepository:
    """Test adapter exercising the public DraftPromotionService seam."""

    def __init__(self, content: dict[str, Any], revision: int = 1) -> None:
        self._content = content
        self._revision = revision
        self._drafts: dict[str, Any] = {}

    def read_official(self, target: DraftTarget):
        return self._snapshot()

    def load_draft(self, draft_id: str, *, actor_id: str | None = None):
        draft = self._drafts.get(draft_id)
        if draft is None or (actor_id is not None and draft.actor_id != actor_id):
            return None
        return draft

    def list_drafts(self, target: DraftTarget, *, actor_id: str | None = None):
        return [
            draft
            for draft in self._drafts.values()
            if draft.target == target and (actor_id is None or draft.actor_id == actor_id)
        ]

    def save_draft(self, draft):
        self._drafts[draft.id] = draft

    def promote_atomically(self, target: DraftTarget, content, *, expected_revision: int, expected_fingerprint: str):
        current = self._snapshot()
        if current.revision != expected_revision or current.fingerprint != expected_fingerprint:
            raise OfficialRevisionConflict(current)
        self._content = content
        self._revision += 1
        return self._snapshot()

    def replace_official(self, content: dict[str, Any]) -> None:
        self._content = content
        self._revision += 1

    def _snapshot(self):
        from server.draft_promotion import OfficialScript, canonical_fingerprint

        return OfficialScript(
            content=self._content, revision=self._revision, fingerprint=canonical_fingerprint(self._content)
        )


@pytest.mark.unit
def test_confirm_promotion_valid_draft_atomically_promotes_official_script() -> None:
    repo = MemoryDraftPromotionRepository({"title": "before", "scenes": []})
    service = DraftPromotionService(repo, token_factory=lambda: "confirm-1", id_factory=lambda: "draft-1")

    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"title": "after", "scenes": []},
        origin="agent",
        actor_id="agent-session-1",
    )

    prepared = service.prepare_promotion(draft.id)
    result = service.confirm_promotion(draft.id, confirmation_token=prepared.confirmation_token or "")

    assert prepared.status == "ready_for_confirmation"
    assert result.status == "promoted"
    assert repo.read_official(draft.target).content == {"title": "after", "scenes": []}


@pytest.mark.unit
def test_prepare_promotion_reports_structured_validation_issues_without_confirmation_token() -> None:
    repo = MemoryDraftPromotionRepository({"title": "before"})
    issue = "title is required"
    service = DraftPromotionService(
        repo,
        validator=lambda content: (
            ()
            if cast(dict[str, Any], content).get("title")
            else (DraftValidationIssue(code="title_required", message=issue, path="/title"),)
        ),
        id_factory=lambda: "draft-invalid",
    )

    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"scenes": []},
        origin="upload",
        actor_id="upload-1",
    )

    prepared = service.prepare_promotion(draft.id)

    assert prepared.status == "invalid"
    assert prepared.confirmation_token is None
    assert prepared.validation_issues[0].code == "title_required"
    assert prepared.validation_issues[0].path == "/title"


@pytest.mark.unit
def test_prepare_promotion_auto_merges_non_overlapping_changes_before_confirmation() -> None:
    repo = MemoryDraftPromotionRepository({"title": "before", "summary": "original"})
    service = DraftPromotionService(repo, token_factory=lambda: "confirm-merge", id_factory=lambda: "draft-merge")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"title": "agent title", "summary": "original"},
        origin="online_ai",
        actor_id="online-ai-1",
    )
    repo.replace_official({"title": "before", "summary": "human summary"})

    prepared = service.prepare_promotion(draft.id)
    result = service.confirm_promotion(draft.id, confirmation_token=prepared.confirmation_token or "")

    assert prepared.status == "ready_for_confirmation"
    assert prepared.auto_merged_paths == ("/summary",)
    assert result.status == "promoted"
    assert repo.read_official(draft.target).content == {"title": "agent title", "summary": "human summary"}


@pytest.mark.unit
def test_prepare_promotion_returns_json_pointer_conflict_for_overlapping_changes() -> None:
    repo = MemoryDraftPromotionRepository({"title": "before"})
    service = DraftPromotionService(repo, id_factory=lambda: "draft-conflict")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"title": "agent title"},
        origin="agent",
        actor_id="agent-session-1",
    )
    repo.replace_official({"title": "human title"})

    prepared = service.prepare_promotion(draft.id)

    assert prepared.status == "conflicted"
    assert prepared.confirmation_token is None
    assert prepared.conflicts == (
        PromotionConflict(path="/title", base_value="before", current_value="human title", draft_value="agent title"),
    )


@pytest.mark.unit
def test_confirm_promotion_rejects_a_stale_confirmation_without_overwriting_newer_script() -> None:
    repo = MemoryDraftPromotionRepository({"title": "before"})
    service = DraftPromotionService(repo, token_factory=lambda: "confirm-stale", id_factory=lambda: "draft-stale")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"title": "agent title"},
        origin="agent",
        actor_id="agent-session-1",
    )
    prepared = service.prepare_promotion(draft.id)
    repo.replace_official({"title": "human title"})

    result = service.confirm_promotion(draft.id, confirmation_token=prepared.confirmation_token or "")

    assert result.status == "stale_confirmation"
    assert repo.read_official(draft.target).content == {"title": "human title"}


@pytest.mark.unit
def test_prepare_promotion_merges_stable_id_collections_by_item() -> None:
    repo = MemoryDraftPromotionRepository(
        {
            "scenes": [
                {"scene_id": "scene-1", "title": "旧标题", "location": "室内"},
                {"scene_id": "scene-2", "title": "第二场", "location": "室外"},
            ]
        }
    )
    service = DraftPromotionService(repo, id_factory=lambda: "draft-stable-merge")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="episode_1.json"),
        content={
            "scenes": [
                {"scene_id": "scene-1", "title": "智能体标题", "location": "室内"},
                {"scene_id": "scene-2", "title": "第二场", "location": "室外"},
            ]
        },
        origin="agent",
        actor_id="user-1",
    )
    repo.replace_official(
        {
            "scenes": [
                {"scene_id": "scene-1", "title": "旧标题", "location": "新地点"},
                {"scene_id": "scene-2", "title": "第二场", "location": "室外"},
            ]
        }
    )

    prepared = service.prepare_promotion(draft.id)

    assert prepared.status == "ready_for_confirmation"
    assert prepared.preview_content == {
        "scenes": [
            {"scene_id": "scene-1", "title": "智能体标题", "location": "新地点"},
            {"scene_id": "scene-2", "title": "第二场", "location": "室外"},
        ]
    }


@pytest.mark.unit
def test_prepare_promotion_conflicts_when_both_sides_change_same_stable_item() -> None:
    repo = MemoryDraftPromotionRepository({"shots": [{"shot_id": "shot-1", "text": "原文"}]})
    service = DraftPromotionService(repo, id_factory=lambda: "draft-stable-conflict")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="episode_1.json"),
        content={"shots": [{"shot_id": "shot-1", "text": "智能体改写"}]},
        origin="agent",
        actor_id="user-1",
    )
    repo.replace_official({"shots": [{"shot_id": "shot-1", "text": "人工改写"}]})

    prepared = service.prepare_promotion(draft.id)

    assert prepared.status == "conflicted"
    assert prepared.conflicts[0].path == "/shots/shot-1/text"


@pytest.mark.unit
def test_prepare_promotion_treats_arrays_without_stable_id_as_atomic_conflicts() -> None:
    repo = MemoryDraftPromotionRepository({"segments": [], "references": ["原始"]})
    service = DraftPromotionService(repo, id_factory=lambda: "draft-unstable-array")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="episode_1.json"),
        content={"segments": [], "references": ["智能体"]},
        origin="agent",
        actor_id="user-1",
    )
    repo.replace_official({"segments": [], "references": ["人工"]})

    prepared = service.prepare_promotion(draft.id)

    assert prepared.status == "conflicted"
    assert prepared.conflicts[0].path == "/references"


@pytest.mark.unit
def test_first_promotion_works_without_a_formal_baseline() -> None:
    repo = MemoryDraftPromotionRepository({}, revision=0)
    service = DraftPromotionService(repo, token_factory=lambda: "confirm-first", id_factory=lambda: "draft-first")
    draft = service.create(
        target=DraftTarget(project_name="demo", script_file="episode_1.json"),
        content={"title": "首次正式稿"},
        origin="agent",
        actor_id="user-1",
    )

    prepared = service.prepare_promotion(draft.id)
    result = service.confirm_promotion(draft.id, confirmation_token=prepared.confirmation_token or "")

    assert draft.base_revision == 0
    assert result.status == "promoted"
    assert repo.read_official(draft.target).content == {"title": "首次正式稿"}


@pytest.mark.unit
def test_draft_lifecycle_update_abandon_and_list() -> None:
    repo = MemoryDraftPromotionRepository({"title": "基线"})
    service = DraftPromotionService(repo, id_factory=iter(["draft-b", "draft-a"]).__next__)
    target = DraftTarget(project_name="demo", script_file="episode_1.json")
    first = service.create(target=target, content={"title": "一"}, origin="agent", actor_id="user-1")
    second = service.create(target=target, content={"title": "二"}, origin="agent", actor_id="user-1")

    updated = service.update(first.id, content={"title": "已更新"})
    abandoned = service.abandon(second.id)

    assert updated.content == {"title": "已更新"}
    assert updated.prepared is None
    assert abandoned.status == "abandoned"
    assert [draft.id for draft in service.list_drafts(target=target)] == ["draft-a", "draft-b"]
    assert service.prepare_promotion(second.id).validation_issues[0].code == "draft_abandoned"
