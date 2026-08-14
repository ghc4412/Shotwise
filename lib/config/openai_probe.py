"""OpenAI 兼容端点（OpenAI Agents SDK 用）的连通性体检 + 诊断分类。

与 ``lib/config/anthropic_probe.py`` 同构：httpx 直调 chat/completions +
models 两个端点，返回同样形状的 ``TestConnectionResponse``，让
``server/routers/agent_config.py`` 按 ``sdk_type`` 选 probe 时共享序列化逻辑。

日志严格只打 URL 与 status，不打 body / headers / api_key。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

import httpx

from lib.agent_provider_catalog import CUSTOM_SENTINEL_ID, get_preset
from lib.config.anthropic_probe import (
    DiagnosisCode,
    ProbeResult,
    TestConnectionResponse,
)
from lib.config.url_utils import ensure_openai_base_url
from lib.httpx_shared import get_http_client

logger = logging.getLogger(__name__)

_ERR_TRUNCATE = 200
_DEFAULT_TEST_MODEL = "gpt-4.1-mini"


async def _post(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    """间接层：测试时 patch 这一个。"""
    client = get_http_client()
    return await client.post(url, headers=headers, json=payload, timeout=timeout_s)


def _truncate(s: str | None) -> str | None:
    if s is None:
        return None
    return s if len(s) <= _ERR_TRUNCATE else s[:_ERR_TRUNCATE] + "…"


async def probe_chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: float = 10.0,
) -> ProbeResult:
    """POST {base_url}/v1/chat/completions 发最小请求 (max_tokens=1)。

    base_url 先经 ``ensure_openai_base_url`` 归一化：用户/预置可能已带 `/v1`
    （如 Agnes ``https://apihub.agnes-ai.com/v1``），直接拼接会得到
    ``/v1/v1/chat/completions`` 这类 404 路径；归一化保证版本段至多出现一次。

    判定:
    - 2xx 且响应 JSON 含 choices 数组 → success
    - 2xx 但响应不像 OpenAI JSON → 判失败 (protocol mismatch)
    - 非 2xx → 失败 (上游错误 body 截 200 字符放入 error 字段)
    - 网络异常/超时 → 失败 (status_code=None)
    """
    effective = ensure_openai_base_url(base_url) or ""
    url = f"{effective.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }
    headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
    started = time.perf_counter()
    try:
        resp = await _post(url=url, headers=headers, payload=payload, timeout_s=timeout_s)
    except httpx.TimeoutException as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.info("probe_chat timeout url=%s elapsed_ms=%d", url, elapsed)
        return ProbeResult(success=False, status_code=None, latency_ms=elapsed, error=f"timeout: {exc!s}")
    except httpx.HTTPError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.info("probe_chat network err url=%s elapsed_ms=%d", url, elapsed)
        return ProbeResult(success=False, status_code=None, latency_ms=elapsed, error=_truncate(str(exc)))

    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info("probe_chat url=%s status=%d elapsed_ms=%d", url, resp.status_code, elapsed)

    if resp.status_code >= 400:
        return ProbeResult(
            success=False,
            status_code=resp.status_code,
            latency_ms=elapsed,
            error=_truncate(resp.text),
        )

    # 2xx：检查是否真的是 OpenAI chat JSON（识别 Anthropic 协议端点冒充）
    try:
        data = resp.json()
    except ValueError:
        return ProbeResult(
            success=False,
            status_code=resp.status_code,
            latency_ms=elapsed,
            error="non-openai response: not JSON",
        )
    if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
        return ProbeResult(
            success=False,
            status_code=resp.status_code,
            latency_ms=elapsed,
            error="non-openai JSON: missing choices array",
        )
    return ProbeResult(success=True, status_code=resp.status_code, latency_ms=elapsed, error=None)


async def _get(*, url: str, headers: dict[str, str], timeout_s: float) -> httpx.Response:
    """间接层：测试时 patch 这一个。"""
    client = get_http_client()
    return await client.get(url, headers=headers, timeout=timeout_s)


async def probe_discovery(
    *,
    base_url: str,
    api_key: str,
    timeout_s: float = 5.0,
) -> ProbeResult:
    """GET {base_url}/v1/models 体检模型发现端点 (warn 级，仅供参考)。

    与 ``probe_chat_completions`` 一致：先 ``ensure_openai_base_url`` 归一化，
    避免已带 `/v1` 的 base_url 拼出 ``/v1/v1/models``。
    """
    effective = ensure_openai_base_url(base_url) or ""
    url = f"{effective.rstrip('/')}/models"
    headers = {"authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    try:
        resp = await _get(url=url, headers=headers, timeout_s=timeout_s)
    except httpx.TimeoutException as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(success=False, status_code=None, latency_ms=elapsed, error=f"timeout: {exc!s}")
    except httpx.HTTPError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(success=False, status_code=None, latency_ms=elapsed, error=_truncate(str(exc)))

    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info("probe_discovery url=%s status=%d", url, resp.status_code)
    success = 200 <= resp.status_code < 300
    return ProbeResult(
        success=success,
        status_code=resp.status_code,
        latency_ms=elapsed,
        error=None if success else _truncate(resp.text),
    )


def classify_probe_failure(result: ProbeResult) -> DiagnosisCode:
    """把失败 ProbeResult 映射到 DiagnosisCode。"""
    if result.success:
        return DiagnosisCode.UNKNOWN  # caller misuse
    err = (result.error or "").lower()
    code = result.status_code
    if code in (401, 403):
        return DiagnosisCode.AUTH_FAILED
    if code == 429:
        return DiagnosisCode.RATE_LIMITED
    # 启发式：404 body 含 "model" 关键词即视为模型不存在；后端改措辞时会退化到 UNKNOWN
    if code == 404 and ("model" in err or "model_not_found" in err):
        return DiagnosisCode.MODEL_NOT_FOUND
    if code is not None and 200 <= code < 300:
        # 2xx 但 probe 判失败 = 协议不匹配（Anthropic 响应冒充 OpenAI）
        return DiagnosisCode.OPENAI_COMPAT_ONLY
    if code is None:
        return DiagnosisCode.NETWORK
    return DiagnosisCode.UNKNOWN


async def run_test(
    *,
    preset_id: str | None,
    base_url: str | None,
    api_key: str,
    model: str | None,
) -> TestConnectionResponse:
    """OpenAI Agents 端到端测试：派生 base_url → chat + models 并发 → 诊断。"""
    if preset_id and preset_id != CUSTOM_SENTINEL_ID:
        preset = get_preset(preset_id)
        if preset is None:
            raise ValueError(f"unknown preset: {preset_id!r}")
        effective_base = base_url or preset.messages_url
        effective_model = model or preset.default_model
    else:
        if not base_url:
            raise ValueError("base_url required for __custom__ mode")
        effective_base = base_url
        effective_model = model or _DEFAULT_TEST_MODEL

    msg, disc = await asyncio.gather(
        probe_chat_completions(base_url=effective_base, api_key=api_key, model=effective_model),
        probe_discovery(base_url=effective_base, api_key=api_key),
    )

    diagnosis: DiagnosisCode | None = None
    if msg.success:
        overall: Literal["ok", "warn", "fail"] = "ok" if (disc is None or disc.success) else "warn"
    else:
        overall = "fail"
        diagnosis = classify_probe_failure(msg)

    return TestConnectionResponse(
        overall=overall,
        messages_probe=msg,
        discovery_probe=disc,
        diagnosis=diagnosis,
        suggestion=None,
        derived_messages_root=effective_base,
        derived_discovery_root=effective_base,
    )
