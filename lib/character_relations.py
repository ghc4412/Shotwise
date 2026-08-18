"""Character relationship data contracts and merge rules.

Relationship data lives at the project level because it describes the story,
not a single character asset.  The module keeps validation and AI/manual merge
semantics in one place so routers, the AI service, and rename/delete flows
share the same rules.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.asset_types import normalize_asset_name, resolve_asset_key

RELATIONSHIP_TYPES = (
    "family",
    "romance",
    "marriage",
    "friend",
    "ally",
    "enemy",
    "mentor",
    "subordinate",
    "rival",
    "interest",
    "custom",
)


class RelationshipEvidence(BaseModel):
    """A compact script reference supporting an AI-generated relationship."""

    model_config = ConfigDict(extra="forbid")

    episode: int | None = Field(default=None, ge=1)
    script_file: str | None = Field(default=None, max_length=255)
    scene_id: str | None = Field(default=None, max_length=255)
    excerpt: str = Field(default="", max_length=500)


class CharacterRelationEdge(BaseModel):
    """One visible relationship line in the character graph."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    type: str = Field(default="custom", max_length=32)
    label: str = Field(default="", max_length=80)
    directed: bool = False
    description: str = Field(default="", max_length=1000)
    origin: Literal["ai", "manual"] = "ai"
    manual_override: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[RelationshipEvidence] = Field(default_factory=list, max_length=8)

    @field_validator("source", "target", "type", "label", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in RELATIONSHIP_TYPES:
            raise ValueError(f"unknown relationship type: {value}")
        return value


class CharacterRelationPosition(BaseModel):
    """Canvas position for one character node."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0
    y: float = 0


class SuppressedRelationshipPair(BaseModel):
    """An AI pair the user removed and should not resurrect on re-analysis."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    directed: bool = False


class CharacterRelationsData(BaseModel):
    """Persisted project-level relationship graph."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(default=0, ge=0)
    analysis_status: Literal["idle", "analyzing", "ready", "failed"] = "idle"
    analyzed_at: str | None = None
    source_fingerprint: str | None = None
    error: str | None = Field(default=None, max_length=1000)
    edges: list[CharacterRelationEdge] = Field(default_factory=list)
    suppressed_pairs: list[SuppressedRelationshipPair] = Field(default_factory=list)
    node_positions: dict[str, CharacterRelationPosition] = Field(default_factory=dict)


def empty_character_relations() -> CharacterRelationsData:
    return CharacterRelationsData()


def pair_key(source: str, target: str, directed: bool) -> tuple[str, str, bool]:
    """Return a canonical pair identity, intentionally independent of relation type."""

    source_key = normalize_asset_name(source)
    target_key = normalize_asset_name(target)
    if not directed and source_key > target_key:
        source_key, target_key = target_key, source_key
    return source_key, target_key, directed


def _resolve_character_name(characters: object, name: str) -> str:
    resolved = resolve_asset_key(characters, name)
    if resolved is None:
        raise ValueError(f"relationship references unknown character: {name}")
    return resolved


def normalize_character_relations(value: object, characters: object) -> CharacterRelationsData:
    """Validate persisted data and resolve every reference to its project key."""

    parsed = CharacterRelationsData.model_validate(value if value is not None else {})
    if not isinstance(characters, dict):
        raise ValueError("characters must be an object before validating relationships")

    ids: set[str] = set()
    relation_keys: set[tuple[str, str, bool, str]] = set()
    normalized_edges: list[CharacterRelationEdge] = []
    for edge in parsed.edges:
        source = _resolve_character_name(characters, edge.source)
        target = _resolve_character_name(characters, edge.target)
        if normalize_asset_name(source) == normalize_asset_name(target):
            raise ValueError("a relationship cannot connect a character to itself")
        if edge.id in ids:
            raise ValueError(f"duplicate relationship id: {edge.id}")
        ids.add(edge.id)
        key_source, key_target, key_directed = pair_key(source, target, edge.directed)
        relation_key = (key_source, key_target, key_directed, edge.type)
        if relation_key in relation_keys:
            raise ValueError("duplicate relationship for the same character pair and type")
        relation_keys.add(relation_key)
        normalized_edges.append(edge.model_copy(update={"source": source, "target": target}))

    suppressed: list[SuppressedRelationshipPair] = []
    seen_suppressed: set[tuple[str, str, bool]] = set()
    for pair in parsed.suppressed_pairs:
        source = _resolve_character_name(characters, pair.source)
        target = _resolve_character_name(characters, pair.target)
        if normalize_asset_name(source) == normalize_asset_name(target):
            continue
        normalized = SuppressedRelationshipPair(source=source, target=target, directed=pair.directed)
        key = pair_key(source, target, pair.directed)
        if key not in seen_suppressed:
            seen_suppressed.add(key)
            suppressed.append(normalized)

    normalized_positions: dict[str, CharacterRelationPosition] = {}
    for name, position in parsed.node_positions.items():
        resolved = resolve_asset_key(characters, name)
        if resolved is not None:
            normalized_positions[resolved] = position

    return parsed.model_copy(
        update={
            "edges": normalized_edges,
            "suppressed_pairs": suppressed,
            "node_positions": normalized_positions,
        }
    )


def relations_payload(data: CharacterRelationsData) -> dict[str, Any]:
    return data.model_dump(mode="json")


def mark_analysis_started(existing: object, characters: object) -> CharacterRelationsData:
    data = normalize_character_relations(existing, characters)
    return data.model_copy(update={"analysis_status": "analyzing", "error": None})


def mark_analysis_failed(existing: object, characters: object, error: str) -> CharacterRelationsData:
    data = normalize_character_relations(existing, characters)
    return data.model_copy(update={"analysis_status": "failed", "error": error[:1000]})


def merge_ai_relationships(
    existing: object,
    characters: object,
    ai_edges: Iterable[CharacterRelationEdge | dict[str, Any]],
    *,
    source_fingerprint: str,
) -> CharacterRelationsData:
    """Replace untouched AI edges while preserving manual edits and deletions."""

    current = normalize_character_relations(existing, characters)
    manual_edges = [edge for edge in current.edges if edge.origin == "manual" or edge.manual_override]
    protected_pairs = {pair_key(edge.source, edge.target, edge.directed) for edge in manual_edges}
    suppressed_pairs = {pair_key(pair.source, pair.target, pair.directed) for pair in current.suppressed_pairs}

    merged_ai: list[CharacterRelationEdge] = []
    seen_keys: set[tuple[str, str, bool, str]] = set()
    for raw_edge in ai_edges:
        edge = (
            raw_edge if isinstance(raw_edge, CharacterRelationEdge) else CharacterRelationEdge.model_validate(raw_edge)
        )
        edge = edge.model_copy(update={"id": str(uuid.uuid4()), "origin": "ai", "manual_override": False})
        normalized = normalize_character_relations(
            {"edges": [edge.model_dump()]},
            characters,
        ).edges[0]
        pair = pair_key(normalized.source, normalized.target, normalized.directed)
        full_key = (*pair, normalized.type)
        if pair in protected_pairs or pair in suppressed_pairs or full_key in seen_keys:
            continue
        seen_keys.add(full_key)
        merged_ai.append(normalized)

    now = datetime.now(UTC).isoformat()
    return current.model_copy(
        update={
            "revision": current.revision + 1,
            "analysis_status": "ready",
            "analyzed_at": now,
            "source_fingerprint": source_fingerprint,
            "error": None,
            "edges": [*manual_edges, *merged_ai],
        }
    )


def apply_manual_relationships(
    existing: object,
    characters: object,
    submitted_edges: Iterable[CharacterRelationEdge | dict[str, Any]],
) -> CharacterRelationsData:
    """Persist a canvas snapshot and identify user edits/deletions.

    Unchanged AI edges remain AI-owned.  Any edited or newly created edge becomes
    manual, while removing an AI edge adds a pair-level suppression record so a
    future AI refresh cannot silently recreate it.
    """

    current = normalize_character_relations(existing, characters)
    old_by_id = {edge.id: edge for edge in current.edges}
    submitted = normalize_character_relations(
        {"edges": [edge.model_dump() if isinstance(edge, CharacterRelationEdge) else edge for edge in submitted_edges]},
        characters,
    ).edges
    submitted_ids = {edge.id for edge in submitted}

    normalized: list[CharacterRelationEdge] = []
    for edge in submitted:
        previous = old_by_id.get(edge.id)
        if previous is None:
            normalized.append(edge.model_copy(update={"origin": "manual", "manual_override": True, "confidence": None}))
            continue
        if _user_visible_edge(previous) != _user_visible_edge(edge):
            normalized.append(
                edge.model_copy(update={"origin": "manual", "manual_override": True, "confidence": previous.confidence})
            )
        else:
            normalized.append(previous)

    suppressions = {pair_key(pair.source, pair.target, pair.directed): pair for pair in current.suppressed_pairs}
    for previous in current.edges:
        if previous.id not in submitted_ids and previous.origin == "ai" and not previous.manual_override:
            key = pair_key(previous.source, previous.target, previous.directed)
            suppressions[key] = SuppressedRelationshipPair(
                source=previous.source,
                target=previous.target,
                directed=previous.directed,
            )

    current_pairs = {pair_key(edge.source, edge.target, edge.directed) for edge in normalized}
    filtered_suppressions = [pair for key, pair in suppressions.items() if key not in current_pairs]
    return current.model_copy(
        update={
            "revision": current.revision + 1,
            "edges": normalized,
            "suppressed_pairs": filtered_suppressions,
        }
    )


def rename_character_relation_references(value: object, old_name: str, new_name: str) -> dict[str, Any] | None:
    """Return relationship data with a character key renamed, or ``None`` if absent."""

    if value is None:
        return None
    parsed = CharacterRelationsData.model_validate(value)

    def renamed(name: str) -> str:
        return new_name if normalize_asset_name(name) == normalize_asset_name(old_name) else name

    return relations_payload(
        parsed.model_copy(
            update={
                "edges": [
                    edge.model_copy(update={"source": renamed(edge.source), "target": renamed(edge.target)})
                    for edge in parsed.edges
                ],
                "suppressed_pairs": [
                    pair.model_copy(update={"source": renamed(pair.source), "target": renamed(pair.target)})
                    for pair in parsed.suppressed_pairs
                ],
                "node_positions": {renamed(name): position for name, position in parsed.node_positions.items()},
            }
        )
    )


def remove_character_relation_references(value: object, name: str) -> dict[str, Any] | None:
    """Remove all graph references to a deleted character."""

    if value is None:
        return None
    parsed = CharacterRelationsData.model_validate(value)
    name_key = normalize_asset_name(name)
    return relations_payload(
        parsed.model_copy(
            update={
                "revision": parsed.revision + 1,
                "edges": [
                    edge
                    for edge in parsed.edges
                    if normalize_asset_name(edge.source) != name_key and normalize_asset_name(edge.target) != name_key
                ],
                "suppressed_pairs": [
                    pair
                    for pair in parsed.suppressed_pairs
                    if normalize_asset_name(pair.source) != name_key and normalize_asset_name(pair.target) != name_key
                ],
                "node_positions": {
                    node_name: position
                    for node_name, position in parsed.node_positions.items()
                    if normalize_asset_name(node_name) != name_key
                },
            }
        )
    )


def relationship_source_fingerprint(project: dict[str, Any], scripts: Iterable[dict[str, Any]]) -> str:
    """Fingerprint the data that should invalidate a previous AI analysis."""

    payload = {
        "overview": project.get("overview") if isinstance(project.get("overview"), dict) else {},
        "characters": project.get("characters") if isinstance(project.get("characters"), dict) else {},
        "scripts": list(scripts),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _user_visible_edge(edge: CharacterRelationEdge) -> tuple[str, str, str, str, bool, str]:
    return (edge.source, edge.target, edge.type, edge.label, edge.directed, edge.description)
