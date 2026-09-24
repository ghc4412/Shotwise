"""create_openai_client 客户端工厂行为。"""

import pytest

from lib.config.url_utils import OFFICIAL_OPENAI_BASE_URL
from lib.openai_shared import create_openai_client

pytestmark = pytest.mark.unit


class TestCreateOpenAIClientBaseURL:
    """base_url 唯一来源为 DB 配置：空值兜死官方端点，环境变量不得静默覆盖路由。"""

    def test_empty_base_url_ignores_env_var(self, monkeypatch):
        # AsyncOpenAI 对空 base_url 会回落读 OPENAI_BASE_URL，工厂须显式兜死官方值
        monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.com/v1")
        client = create_openai_client(api_key="x", base_url=None)
        assert str(client.base_url).rstrip("/") == OFFICIAL_OPENAI_BASE_URL.rstrip("/")

    def test_whitespace_base_url_ignores_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.com/v1")
        client = create_openai_client(api_key="x", base_url="   ")
        assert str(client.base_url).rstrip("/") == OFFICIAL_OPENAI_BASE_URL.rstrip("/")

    def test_explicit_base_url_preserved(self, monkeypatch):
        # 显式 base_url 原样透传，不被环境变量或官方默认值篡改
        monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.com/v1")
        client = create_openai_client(api_key="x", base_url="https://vllm.internal:8000/v1")
        assert str(client.base_url).rstrip("/") == "https://vllm.internal:8000/v1"


class TestCreateOpenAIClientForwarding:
    """max_retries / timeout 只在显式给出时下传，未声明时不覆盖 SDK 默认。"""

    @staticmethod
    def _capture(monkeypatch, **kwargs) -> dict:
        captured: dict = {}

        class _StubClient:
            def __init__(self, **kw):
                captured.update(kw)

        monkeypatch.setattr("lib.openai_shared.AsyncOpenAI", _StubClient)
        create_openai_client(**kwargs)
        return captured

    def test_explicit_values_forwarded(self, monkeypatch):
        captured = self._capture(monkeypatch, api_key="k", base_url="https://x/v1", max_retries=0, timeout=180.0)
        assert captured["max_retries"] == 0
        assert captured["timeout"] == 180.0

    def test_omitted_values_not_forwarded(self, monkeypatch):
        captured = self._capture(monkeypatch, api_key="k")
        assert "max_retries" not in captured
        assert "timeout" not in captured
