"""出站 URL 的统一形态校验入口。

探针、模型发现、声明式运行时请求与产物下载在真正发起 HTTP 之前都经过这里，避免同一份
用户配置在不同入口得到不同结论（例如「发现模型能过、真跑生成被拒」）。

刻意不限制私网 / 环回地址：自建服务、局域网中转与 ``http://localhost`` 上的本地网关都是
受支持的端点形态，与自定义供应商 base_url 不限 scheme 的既有约定一致；收窄到公网会让这
类场景整体不可用。本模块只做形态校验——scheme / host / userinfo / 端口 / query——把非法
形态挡在 httpx 之前，而不是代替用户判断某个地址是否可信。
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

__all__ = [
    "OutboundUrlError",
    "validate_outbound_base_url",
    "validate_outbound_url",
]

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class OutboundUrlError(ValueError):
    """出站地址不是绝对的 http(s) URL，或带 userinfo / query / fragment / 非法端口。

    消息为固定文案，不回显输入：地址可能内嵌凭证（用户把 key 拼进 URL），原文外流会把
    凭证写进日志与接口响应。
    """


def validate_outbound_url(raw: str) -> str:
    """校验产物下载 / 已拼好路径的出站 URL，返回去空白后的原值。

    query 放行：供应商签发的产物地址通常把签名参数挂在 query 上，收窄会导致下载断裂。
    fragment 仍拦——它在链路中不可见，只会让「存储值即调用值」出现无意义的偏差。
    """
    return _validate(raw, allow_query=True)


def validate_outbound_base_url(raw: str) -> str:
    """校验用户配置的端点根（base_url），返回去空白后的原值。

    比 :func:`validate_outbound_url` 多拦 query：调用方按字符串拼接路径，带 query 会让
    拼出的地址与「存储值即调用值」分叉（探测通过但运行时 404）。
    """
    return _validate(raw, allow_query=False)


def _validate(raw: str, *, allow_query: bool) -> str:
    if not isinstance(raw, str):
        raise OutboundUrlError("outbound url must be a string")
    candidate = raw.strip()
    if not candidate:
        raise OutboundUrlError("outbound url is empty")
    # 逐字符拦而不只看 urlparse 的 query / fragment 是否非空：空 query 的
    # ``https://x/a?`` 同样会让拼接结果与存储值分叉。
    if "#" in candidate:
        raise OutboundUrlError("outbound url must not carry fragment")
    if not allow_query and "?" in candidate:
        raise OutboundUrlError("outbound url must not carry query")
    parsed = urlparse(candidate)
    try:
        has_userinfo = bool(parsed.username or parsed.password)
        host = parsed.hostname
        _ = parsed.port  # netloc 惰性解析，非法端口在这一步才抛 ValueError
        httpx.URL(candidate)
    except (ValueError, httpx.InvalidURL) as exc:
        raise OutboundUrlError("outbound url is not a parsable URL") from exc
    if has_userinfo:
        raise OutboundUrlError("outbound url must not carry userinfo")
    if parsed.scheme not in _ALLOWED_SCHEMES or not host:
        raise OutboundUrlError("outbound url must be an absolute http(s) URL")
    return candidate
