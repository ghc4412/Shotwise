from __future__ import annotations

import pytest

from server.services.workflow_contracts import validate_workflow_template_contract

pytestmark = pytest.mark.unit


def test_workflow_contract_accepts_media_asset_ids():
    result = validate_workflow_template_contract(
        {
            "nodes": [
                {
                    "node_key": "input",
                    "media_asset_id": "asset-123",
                    "media_asset_ids": ["asset-456"],
                }
            ],
            "edges": [],
        }
    )

    assert result["valid"] is True
