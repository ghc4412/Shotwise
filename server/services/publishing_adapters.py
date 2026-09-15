"""Platform adapter contracts and capability declarations.

No network client is implemented here. Real adapters must be added only after
an official platform API, application credentials, and scopes are confirmed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from lib.db.models.publish import PublishJob


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    platform: str
    display_name: str
    adapter_connected: bool
    supports_oauth: bool
    supports_publish: bool
    supports_schedule: bool
    supports_status_polling: bool
    supports_retract: bool
    supports_cover_update: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PublishSubmission:
    external_content_id: str
    external_status: str


@dataclass(frozen=True, slots=True)
class PublishStatus:
    external_status: str
    published: bool = False
    failed: bool = False
    retryable: bool = False
    error_code: str | None = None
    error_message: str | None = None


class PublishingAdapter(Protocol):
    capabilities: PlatformCapabilities

    async def submit(self, job: PublishJob) -> PublishSubmission: ...

    async def poll(self, job: PublishJob) -> PublishStatus: ...

    async def retract(self, job: PublishJob) -> None: ...


_PLATFORM_CAPABILITIES: dict[str, PlatformCapabilities] = {
    "douyin": PlatformCapabilities(
        platform="douyin",
        display_name="抖音",
        adapter_connected=False,
        supports_oauth=False,
        supports_publish=False,
        supports_schedule=False,
        supports_status_polling=False,
        supports_retract=False,
        supports_cover_update=False,
        unavailable_reason="official_adapter_not_connected",
    ),
    "hongguo": PlatformCapabilities(
        platform="hongguo",
        display_name="红果",
        adapter_connected=False,
        supports_oauth=False,
        supports_publish=False,
        supports_schedule=False,
        supports_status_polling=False,
        supports_retract=False,
        supports_cover_update=False,
        unavailable_reason="official_adapter_not_connected",
    ),
}

# Keep runtime adapter registration separate from capability declarations. A
# platform can be advertised before its official adapter is connected; in
# that case lookup must safely return None rather than inventing a client.
_PLATFORM_ADAPTERS: dict[str, PublishingAdapter | None] = {platform: None for platform in _PLATFORM_CAPABILITIES}


def _normalize_platform(platform: str) -> str:
    return platform.strip().lower()


def list_platform_capabilities() -> list[dict[str, object]]:
    return [asdict(capability) for capability in _PLATFORM_CAPABILITIES.values()]


def get_platform_capabilities(platform: str) -> PlatformCapabilities | None:
    return _PLATFORM_CAPABILITIES.get(_normalize_platform(platform))


def get_publishing_adapter(platform: str) -> PublishingAdapter | None:
    """Return the explicitly registered adapter for a supported platform.

    The built-in registry intentionally contains no network clients. Until an
    official adapter is registered, both mainland platforms resolve to None
    and callers can fail closed without attempting publication.
    """
    return _PLATFORM_ADAPTERS.get(_normalize_platform(platform))


def register_publishing_adapter(
    platform: str,
    adapter: PublishingAdapter | None,
) -> None:
    """Register or clear an adapter for a declared platform.

    Registration is explicit so tests and a future official integration can
    inject an adapter without changing the default registry. The adapter must
    describe the same normalized platform as its registry slot.
    """
    normalized_platform = _normalize_platform(platform)
    if normalized_platform not in _PLATFORM_CAPABILITIES:
        raise ValueError(f"unsupported publishing platform: {platform!r}")
    if adapter is not None:
        adapter_platform = _normalize_platform(adapter.capabilities.platform)
        if adapter_platform != normalized_platform:
            raise ValueError(
                "publishing adapter platform does not match registry slot: "
                f"{adapter.capabilities.platform!r} != {platform!r}"
            )
    _PLATFORM_ADAPTERS[normalized_platform] = adapter


def supported_platforms() -> frozenset[str]:
    return frozenset(_PLATFORM_CAPABILITIES)


__all__ = [
    "PlatformCapabilities",
    "PublishStatus",
    "PublishSubmission",
    "PublishingAdapter",
    "get_platform_capabilities",
    "get_publishing_adapter",
    "list_platform_capabilities",
    "register_publishing_adapter",
    "supported_platforms",
]
