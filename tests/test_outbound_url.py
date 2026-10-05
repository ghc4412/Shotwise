"""outbound_url：出站 URL 形态校验（scheme / host / userinfo / query / fragment / 端口）。"""

import pytest

from lib.outbound_url import (
    OutboundUrlError,
    validate_outbound_base_url,
    validate_outbound_url,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw",
    [
        "https://api.example.com/v1",
        "http://localhost:11434/v1",
        "http://10.0.0.5:8000",
        "  https://api.example.com/v1  ",
    ],
)
def test_base_url_accepts_absolute_http_endpoints(raw: str):
    assert validate_outbound_base_url(raw) == raw.strip()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url",
        "file:///etc/passwd",
        "//h.com/v1",
        "https://user:pass@h.com/v1",
        "https://h.com/v1?a=b",
        "https://h.com/v1?",
        "https://h.com/v1#frag",
        "https://h.com:99999/v1",
        "ftp://h.com/x",
    ],
)
def test_base_url_rejects_malformed_endpoints(raw: str):
    with pytest.raises(OutboundUrlError):
        validate_outbound_base_url(raw)


def test_product_url_allows_query_signature():
    # 供应商签发的产物地址把签名参数挂在 query 上，收窄会导致下载断裂
    raw = "https://cdn.example.com/a.mp4?X-Signature=abc&Expires=1"
    assert validate_outbound_url(raw) == raw


def test_product_url_rejects_fragment():
    with pytest.raises(OutboundUrlError):
        validate_outbound_url("https://cdn.example.com/a.mp4#frag")


def test_product_url_rejects_userinfo():
    with pytest.raises(OutboundUrlError):
        validate_outbound_url("https://u:p@cdn.example.com/a.mp4")


def test_error_message_does_not_echo_input():
    # 用户可能把 key 拼进 URL，异常文案不能回显原文
    secret = "https://user:leaked-secret@api.example.com/v1"
    with pytest.raises(OutboundUrlError) as excinfo:
        validate_outbound_base_url(secret)
    assert "leaked-secret" not in str(excinfo.value)
