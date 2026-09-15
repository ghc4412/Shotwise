from __future__ import annotations

import dataclasses

import pytest

from server.services.publishing_adapters import (
    PlatformCapabilities,
    PublishStatus,
    PublishSubmission,
    get_platform_capabilities,
    get_publishing_adapter,
    list_platform_capabilities,
    register_publishing_adapter,
    supported_platforms,
)

pytestmark = pytest.mark.unit


def test_declared_platforms_are_mainland_first_and_not_connected() -> None:
    assert supported_platforms() == {"douyin", "hongguo"}

    capabilities = list_platform_capabilities()
    assert [item["platform"] for item in capabilities] == ["douyin", "hongguo"]
    assert [item["display_name"] for item in capabilities] == ["抖音", "红果"]
    assert all(item["adapter_connected"] is False for item in capabilities)
    assert all(item["supports_publish"] is False for item in capabilities)
    assert all(item["unavailable_reason"] == "official_adapter_not_connected" for item in capabilities)


def test_capability_lookup_normalizes_platform_name() -> None:
    assert get_platform_capabilities(" DOUYIN ") == get_platform_capabilities("douyin")
    assert get_platform_capabilities("unknown") is None


def test_capabilities_are_dataclasses_without_dict_requirement() -> None:
    capability = get_platform_capabilities("douyin")
    assert capability is not None
    assert dataclasses.asdict(capability)["platform"] == "douyin"
    assert not hasattr(capability, "__dict__")


class _FakeAdapter:
    capabilities = PlatformCapabilities(
        platform="douyin",
        display_name="抖音",
        adapter_connected=True,
        supports_oauth=True,
        supports_publish=True,
        supports_schedule=False,
        supports_status_polling=True,
        supports_retract=True,
        supports_cover_update=False,
    )

    async def submit(self, job) -> PublishSubmission:
        return PublishSubmission(external_content_id=job.id, external_status="submitted")

    async def poll(self, job) -> PublishStatus:
        return PublishStatus(external_status="published", published=True)

    async def retract(self, job) -> None:
        return None


def test_adapter_registry_is_unconnected_by_default_and_supports_explicit_injection() -> None:
    assert get_publishing_adapter(" DOUYIN ") is None
    adapter = _FakeAdapter()

    register_publishing_adapter("douyin", adapter)
    try:
        assert get_publishing_adapter("douyin") is adapter
        assert get_publishing_adapter("hongguo") is None
    finally:
        register_publishing_adapter("douyin", None)


def test_adapter_registry_rejects_unknown_or_mismatched_platform() -> None:
    adapter = _FakeAdapter()

    with pytest.raises(ValueError, match="unsupported publishing platform"):
        register_publishing_adapter("unknown", adapter)
    with pytest.raises(ValueError, match="does not match"):
        register_publishing_adapter("hongguo", adapter)
