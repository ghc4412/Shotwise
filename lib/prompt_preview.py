"""Safe prompt preview snapshots captured at task admission.

The queue stores the snapshot beside the task payload so the task detail API can
show what was actually admitted without exposing provider credentials or making
the UI reconstruct a request from mutable project data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROMPT_PREVIEW_PAYLOAD_KEY = "__shotwise_prompt_preview"
"""Internal payload key; removed from the public task payload projection."""

_REDACTED = "[REDACTED]"
_MAX_PROMPT_CHARS = 4096
_MAX_IDENTIFIER_CHARS = 256
_MAX_SCRIPT_FILE_CHARS = 512
_MAX_REFERENCE_KIND_CHARS = 64
_MAX_REFERENCE_LABEL_CHARS = 256
_MAX_REFERENCE_VALUE_CHARS = 1024
_MAX_NOTE_CHARS = 512
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(?P<scheme>bearer|basic)\s+[a-z0-9._~+/=-]+")
_INLINE_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?P<key>access[_-]?token|api[_-]?key|authorization|client[_-]?secret|password|refresh[_-]?token|secret|token)"
    r"(?P<separator>\s*[:=]\s*)(?P<quote>['\"]?)[^\s,'\"&}]+(?P=quote)"
)
_SENSITIVE_KEY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "set_cookie",
    "signature",
    "token",
    "key",
}


def _bounded_text(value: object, limit: int) -> str:
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key).strip()).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEY_NAMES or any(
        normalized.endswith(f"_{suffix}") for suffix in ("key", "token", "secret", "password", "credential")
    )


def _redact_url(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        trailing = ""
        while candidate and candidate[-1] in ".,;:!?)]}":
            trailing = candidate[-1] + trailing
            candidate = candidate[:-1]
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return match.group(0)
        query = urlencode([(key, _REDACTED) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)])
        fragment = _REDACTED if parsed.fragment else ""
        netloc = parsed.netloc
        if parsed.username or parsed.password:
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parsed.port:
                netloc += f":{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment)) + trailing

    value = _AUTH_SCHEME_PATTERN.sub(lambda match: f"{match.group('scheme')} {_REDACTED}", value)
    value = _INLINE_CREDENTIAL_PATTERN.sub(
        lambda match: (
            f"{match.group('key')}{match.group('separator')}{match.group('quote')}{_REDACTED}{match.group('quote')}"
        ),
        value,
    )
    return _URL_PATTERN.sub(replace, value)


def _sanitize_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _REDACTED if _is_sensitive_key(key) else _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_sanitize_value(item) for item in value[:32]]
    if isinstance(value, str):
        return _redact_url(value)
    return value


def _prompt_text(value: object) -> tuple[str, str]:
    if isinstance(value, str):
        return _bounded_text(_redact_url(value), _MAX_PROMPT_CHARS), "plain_text"
    if isinstance(value, Mapping):
        try:
            sanitized = _sanitize_value(value)
            text = json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True)
            return _bounded_text(text, _MAX_PROMPT_CHARS), "structured"
        except (TypeError, ValueError):
            return "", "unknown"
    return ("" if value is None else _bounded_text(_redact_url(value), _MAX_PROMPT_CHARS)), "unknown"


def _provider_and_model(provider_id: str | None, payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    provider = provider_id or None
    model: str | None = None
    for key in ("video_provider_i2v", "video_provider_r2v", "image_provider_t2i", "image_provider_i2i"):
        value = payload.get(key)
        if not isinstance(value, str) or "/" not in value:
            continue
        candidate_provider, candidate_model = value.split("/", 1)
        if candidate_provider and candidate_model:
            provider = provider or candidate_provider
            model = candidate_model
            break
    return provider, model


def _references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:32]:
        if isinstance(item, Mapping):
            label = item.get("label") or item.get("name") or item.get("id")
            raw_value = item.get("value") or item.get("url") or item.get("path") or item.get("id")
            if isinstance(raw_value, str) and raw_value:
                result.append(
                    {
                        "kind": _bounded_text(
                            _redact_url(str(item.get("kind") or item.get("type") or "other")),
                            _MAX_REFERENCE_KIND_CHARS,
                        ),
                        "label": _bounded_text(_redact_url(str(label or raw_value)), _MAX_REFERENCE_LABEL_CHARS),
                        "value": _bounded_text(_redact_url(raw_value), _MAX_REFERENCE_VALUE_CHARS),
                    }
                )
        elif isinstance(item, str) and item:
            sanitized = _bounded_text(_redact_url(item), _MAX_REFERENCE_VALUE_CHARS)
            result.append({"kind": "other", "label": sanitized[:_MAX_REFERENCE_LABEL_CHARS], "value": sanitized})
    return result


def build_enqueue_prompt_preview(
    *,
    project_name: str,
    task_type: str,
    media_type: str,
    resource_id: str,
    script_file: str | None,
    provider_id: str | None,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded, provider-agnostic preview for one admitted task.

    This is intentionally not a provider payload serializer. Provider-specific
    normalization still happens at execution time, while this snapshot records
    the immutable enqueue inputs and the safe metadata known at admission.
    """
    original_prompt, shape = _prompt_text(payload.get("prompt"))
    provider, model = _provider_and_model(provider_id, payload)
    provider = _bounded_text(_redact_url(provider), _MAX_IDENTIFIER_CHARS) if provider else None
    model = _bounded_text(_redact_url(model), _MAX_IDENTIFIER_CHARS) if model else None
    references = _references(payload.get("references"))
    summary: dict[str, Any] = {
        "project_name": _bounded_text(_redact_url(project_name), _MAX_IDENTIFIER_CHARS),
        "task_type": _bounded_text(_redact_url(task_type), _MAX_IDENTIFIER_CHARS),
        "media_type": _bounded_text(_redact_url(media_type), _MAX_IDENTIFIER_CHARS),
        "resource_id": _bounded_text(_redact_url(resource_id), _MAX_IDENTIFIER_CHARS),
    }
    if script_file:
        summary["script_file"] = _bounded_text(_redact_url(script_file), _MAX_SCRIPT_FILE_CHARS)

    request: dict[str, Any] = {
        "id": _bounded_text(_redact_url(resource_id), _MAX_IDENTIFIER_CHARS),
        "label": _bounded_text(_redact_url(f"{task_type}:{resource_id}"), _MAX_IDENTIFIER_CHARS),
        "original_prompt": original_prompt,
        "effective_prompt": original_prompt or None,
        "shape": shape,
        "provider": provider,
        "model": model,
        "references": references,
        "duration_seconds": payload.get("duration_seconds")
        if isinstance(payload.get("duration_seconds"), (int, float))
        and not isinstance(payload.get("duration_seconds"), bool)
        else None,
        "resolution": _bounded_text(_redact_url(payload["resolution"]), _MAX_IDENTIFIER_CHARS)
        if isinstance(payload.get("resolution"), str)
        else None,
        "capability_adjustments": [
            _bounded_text(_redact_url(item), _MAX_NOTE_CHARS)
            for item in payload.get("capability_adjustments", [])[:32]
            if isinstance(item, str)
        ]
        if isinstance(payload.get("capability_adjustments"), list)
        else [],
        "warnings": [
            _bounded_text(_redact_url(item), _MAX_NOTE_CHARS)
            for item in payload.get("warnings", [])[:32]
            if isinstance(item, str)
        ]
        if isinstance(payload.get("warnings"), list)
        else [],
        "request_summary": summary,
    }
    return {"source": "enqueue_snapshot", "requests": [request]}


__all__ = ["PROMPT_PREVIEW_PAYLOAD_KEY", "build_enqueue_prompt_preview"]
