"""openai_probe（OpenAI Agents 连接测试）单元测试。"""

from __future__ import annotations

import pytest

from lib.config import openai_probe
from lib.config.anthropic_probe import DiagnosisCode, ProbeResult

pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", json_data: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self) -> dict:
        if self._json_data is None:
            raise ValueError("not json")
        return self._json_data


@pytest.mark.asyncio
async def test_probe_chat_success(monkeypatch) -> None:
    async def fake_post(**kwargs):
        return _FakeResponse(200, json_data={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(openai_probe, "_post", fake_post)
    result = await openai_probe.probe_chat_completions(
        base_url="https://api.deepseek.com", api_key="sk", model="deepseek-chat"
    )
    assert result.success is True
    assert result.status_code == 200
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_probe_chat_auth_failed(monkeypatch) -> None:
    async def fake_post(**kwargs):
        return _FakeResponse(401, text="invalid api key")

    monkeypatch.setattr(openai_probe, "_post", fake_post)
    result = await openai_probe.probe_chat_completions(
        base_url="https://api.deepseek.com", api_key="bad", model="deepseek-chat"
    )
    assert result.success is False
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_probe_chat_non_openai_json(monkeypatch) -> None:
    async def fake_post(**kwargs):
        return _FakeResponse(200, json_data={"type": "message"})  # Anthropic 形状

    monkeypatch.setattr(openai_probe, "_post", fake_post)
    result = await openai_probe.probe_chat_completions(base_url="https://x", api_key="sk", model="m")
    assert result.success is False
    assert "choices" in (result.error or "")


def test_classify_probe_failure() -> None:
    assert openai_probe.classify_probe_failure(ProbeResult(False, 401, None, "auth")) == DiagnosisCode.AUTH_FAILED
    assert openai_probe.classify_probe_failure(ProbeResult(False, 429, None, "rate")) == DiagnosisCode.RATE_LIMITED
    assert (
        openai_probe.classify_probe_failure(ProbeResult(False, 404, None, "model not found"))
        == DiagnosisCode.MODEL_NOT_FOUND
    )
    assert (
        openai_probe.classify_probe_failure(ProbeResult(False, 200, None, "non-openai"))
        == DiagnosisCode.OPENAI_COMPAT_ONLY
    )
    assert openai_probe.classify_probe_failure(ProbeResult(False, None, None, "timeout")) == DiagnosisCode.NETWORK


@pytest.mark.asyncio
async def test_run_test_preset(monkeypatch) -> None:
    async def fake_chat(**kwargs):
        return ProbeResult(success=True, status_code=200, latency_ms=8, error=None)

    async def fake_disc(**kwargs):
        return ProbeResult(success=True, status_code=200, latency_ms=5, error=None)

    monkeypatch.setattr(openai_probe, "probe_chat_completions", fake_chat)
    monkeypatch.setattr(openai_probe, "probe_discovery", fake_disc)
    result = await openai_probe.run_test(preset_id="deepseek-openai", base_url=None, api_key="sk", model=None)
    assert result.overall == "ok"
    assert result.derived_messages_root == "https://api.deepseek.com"
    assert result.messages_probe.success is True


@pytest.mark.asyncio
async def test_probe_chat_avoids_duplicate_v1(monkeypatch) -> None:
    """base_url 已带 /v1(如 Agnes 预置)时不再重复拼接，避免 /v1/v1 404。"""
    captured: dict[str, str] = {}

    async def fake_post(**kwargs):
        captured["url"] = kwargs["url"]
        return _FakeResponse(200, json_data={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(openai_probe, "_post", fake_post)
    result = await openai_probe.probe_chat_completions(
        base_url="https://apihub.agnes-ai.com/v1", api_key="sk", model="agnes-2.0-flash"
    )
    assert captured["url"] == "https://apihub.agnes-ai.com/v1/chat/completions"
    assert result.success is True


@pytest.mark.asyncio
async def test_probe_discovery_avoids_duplicate_v1(monkeypatch) -> None:
    async def fake_get(**kwargs):
        return _FakeResponse(200, json_data={"data": []})

    monkeypatch.setattr(openai_probe, "_get", fake_get)
    result = await openai_probe.probe_discovery(base_url="https://apihub.agnes-ai.com/v1", api_key="sk")
    assert result.success is True


@pytest.mark.asyncio
async def test_probe_chat_appends_v1_when_root_base(monkeypatch) -> None:
    """根级 base_url(无版本段)仍按旧行为补 /v1，兼容 DeepSeek 等预置。"""
    captured: dict[str, str] = {}

    async def fake_post(**kwargs):
        captured["url"] = kwargs["url"]
        return _FakeResponse(200, json_data={"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(openai_probe, "_post", fake_post)
    await openai_probe.probe_chat_completions(base_url="https://api.deepseek.com", api_key="sk", model="deepseek-chat")
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_run_test_custom_requires_base_url() -> None:
    with pytest.raises(ValueError):
        await openai_probe.run_test(preset_id="__custom__", base_url=None, api_key="sk", model=None)
