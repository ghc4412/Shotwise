from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_media_asset_migration_is_chained_and_index_only():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "p5_media_assets.py"
    source = path.read_text(encoding="utf-8")
    assert 'revision = "p5_media_assets"' in source
    assert '"media_assets"' in source
    assert '"media_bindings"' in source
    assert '"media_derivations"' in source
    assert "physical_path" in source
    assert "down_revision" in source
