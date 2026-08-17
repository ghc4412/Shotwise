import pytest

from lib.character_relations import (
    apply_manual_relationships,
    merge_ai_relationships,
    normalize_character_relations,
    remove_character_relation_references,
    rename_character_relation_references,
)


def _edge(source: str, target: str, *, edge_id: str = "ai-1", origin: str = "ai", label: str = "") -> dict[str, object]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": "ally",
        "label": label,
        "directed": False,
        "description": "",
        "origin": origin,
        "manual_override": origin == "manual",
        "confidence": 0.8 if origin == "ai" else None,
        "evidence": [],
    }


@pytest.mark.unit
def test_ai_merge_preserves_manual_override_and_suppression() -> None:
    characters = {"Alice": {}, "Bob": {}, "Cara": {}}
    existing = {
        "revision": 2,
        "edges": [
            _edge("Alice", "Bob", edge_id="manual-1", origin="manual", label="old label"),
            _edge("Alice", "Cara", edge_id="ai-1"),
        ],
        "suppressed_pairs": [{"source": "Bob", "target": "Cara", "directed": False}],
    }
    merged = merge_ai_relationships(
        existing,
        characters,
        [
            _edge("Alice", "Bob", edge_id="new-ai"),
            _edge("Alice", "Cara", edge_id="new-ai-2"),
            _edge("Bob", "Cara", edge_id="new-ai-3"),
        ],
        source_fingerprint="fp",
    )
    assert [(edge.source, edge.target, edge.origin) for edge in merged.edges] == [
        ("Alice", "Bob", "manual"),
        ("Alice", "Cara", "ai"),
    ]
    assert merged.revision == 3
    assert merged.source_fingerprint == "fp"


@pytest.mark.unit
def test_manual_delete_records_ai_pair_suppression_and_new_edges_are_manual() -> None:
    characters = {"Alice": {}, "Bob": {}, "Cara": {}}
    existing = {"revision": 1, "edges": [_edge("Alice", "Bob")], "suppressed_pairs": []}
    saved = apply_manual_relationships(existing, characters, [_edge("Alice", "Cara", edge_id="new")])
    assert len(saved.edges) == 1
    assert saved.edges[0].origin == "manual"
    assert {(pair.source, pair.target) for pair in saved.suppressed_pairs} == {("Alice", "Bob")}


@pytest.mark.unit
def test_character_reference_cascade_and_validation() -> None:
    characters = {"Alice": {}, "Bob": {}}
    data = {"edges": [_edge("Alice", "Bob")], "suppressed_pairs": []}
    renamed = rename_character_relation_references(data, "Alice", "Alicia")
    assert renamed is not None
    assert renamed["edges"][0]["source"] == "Alicia"
    removed = remove_character_relation_references(renamed, "Bob")
    assert removed is not None
    assert removed["edges"] == []
    assert normalize_character_relations({"edges": []}, characters).revision == 0
