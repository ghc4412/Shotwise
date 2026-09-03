"""Agent provider transport protocol identifiers and validation helpers."""

from __future__ import annotations

PROTOCOL_CHAT_COMPLETIONS = "chat_completions"
PROTOCOL_RESPONSES = "responses"
PROTOCOL_ANTHROPIC_MESSAGES = "anthropic_messages"

OPENAI_PROTOCOLS = (PROTOCOL_CHAT_COMPLETIONS, PROTOCOL_RESPONSES)
AGENT_PROTOCOLS = (*OPENAI_PROTOCOLS, PROTOCOL_ANTHROPIC_MESSAGES)


def default_protocol(sdk_type: str) -> str:
    """Return the transport used by legacy credentials without a protocol column."""
    return PROTOCOL_ANTHROPIC_MESSAGES if sdk_type == "claude" else PROTOCOL_CHAT_COMPLETIONS


def normalize_protocol(sdk_type: str, protocol: str | None) -> str:
    """Validate that an Agent SDK type and transport protocol are compatible."""
    value = (protocol or default_protocol(sdk_type)).strip()
    if sdk_type == "claude":
        if value != PROTOCOL_ANTHROPIC_MESSAGES:
            raise ValueError(f"protocol {value!r} is not valid for Claude Agent SDK")
        return value
    if sdk_type == "openai":
        if value not in OPENAI_PROTOCOLS:
            raise ValueError(f"protocol {value!r} is not valid for OpenAI Agents SDK")
        return value
    raise ValueError(f"unknown Agent SDK type: {sdk_type!r}")
