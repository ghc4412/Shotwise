"""Ark 客户端共享工厂测试。"""

from unittest.mock import MagicMock, patch

import pytest

from lib.ark_shared import create_ark_client


@pytest.mark.unit
def test_create_ark_client_does_not_inherit_environment_proxy() -> None:
    with (
        patch("volcenginesdkarkruntime.Ark") as ark_cls,
        patch("lib.ark_shared.httpx.Client") as http_client_cls,
    ):
        client = create_ark_client(api_key="test-key")

    http_client_cls.assert_called_once_with(trust_env=False)
    ark_cls.assert_called_once_with(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="test-key",
        http_client=http_client_cls.return_value,
    )
    assert client is ark_cls.return_value


@pytest.mark.unit
def test_create_ark_client_preserves_explicit_base_url() -> None:
    with (
        patch("volcenginesdkarkruntime.Ark") as ark_cls,
        patch("lib.ark_shared.httpx.Client") as http_client_cls,
    ):
        create_ark_client(api_key="test-key", base_url="https://relay.example/api/v3")

    ark_cls.assert_called_once_with(
        base_url="https://relay.example/api/v3",
        api_key="test-key",
        http_client=http_client_cls.return_value,
    )


@pytest.mark.unit
def test_ark_text_backend_does_not_inherit_environment_proxy() -> None:
    with (
        patch("lib.text_backends.ark.create_ark_client", return_value=MagicMock()),
        patch("lib.text_backends.ark.OpenAI") as openai_cls,
        patch("lib.text_backends.ark.httpx.Client") as http_client_cls,
    ):
        from lib.text_backends.ark import ArkTextBackend

        ArkTextBackend(api_key="test-key")

    assert http_client_cls.call_count == 1
    http_client_cls.assert_called_once_with(trust_env=False)
    openai_cls.assert_called_once_with(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="test-key",
        http_client=http_client_cls.return_value,
    )
