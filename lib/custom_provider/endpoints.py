"""ENDPOINT_REGISTRY — 自定义供应商可用 endpoint 单一真相源。

每条 endpoint 是一个 EndpointSpec，绑定 media_type、family、HTTP 调用形态与 build_backend 闭包。
factory.create_custom_backend 通过 endpoint 字符串查表派发；
server.routers.custom_providers 通过 GET /custom-providers/endpoints 把目录暴露给前端，
让前端的下拉选项、路径展示完全派生自此真相源。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import quote, urlsplit

from lib.audio_backends.openai import OpenAIAudioBackend
from lib.config.url_utils import ensure_google_base_url, ensure_openai_base_url
from lib.custom_provider.backends import (
    CustomAudioBackend,
    CustomImageBackend,
    CustomTextBackend,
    CustomVideoBackend,
)
from lib.image_backends.base import ImageCapability
from lib.image_backends.dashscope import DashScopeImageBackend
from lib.image_backends.gemini import GeminiImageBackend
from lib.image_backends.kling import KlingImageBackend
from lib.image_backends.minimax import MiniMaxImageBackend
from lib.image_backends.openai import OpenAIImageBackend
from lib.text_backends.gemini import GeminiTextBackend
from lib.text_backends.openai import OpenAITextBackend
from lib.video_backends.ark import ArkVideoBackend
from lib.video_backends.base import VideoCapabilities
from lib.video_backends.dashscope import DashScopeVideoBackend
from lib.video_backends.kling import KlingVideoBackend
from lib.video_backends.minimax import MiniMaxVideoBackend
from lib.video_backends.newapi import NewAPIVideoBackend
from lib.video_backends.openai import OpenAIVideoBackend
from lib.video_backends.v2_video_generations import V2VideoGenerationsBackend
from lib.video_backends.vidu import ViduVideoBackend

if TYPE_CHECKING:
    from lib.db.models.custom_provider import CustomProvider


# ── EndpointSpec 数据类型 ───────────────────────────────────────────


@dataclass(frozen=True)
class EndpointSpec:
    """单条 endpoint 的元数据 + backend 构造闭包。"""

    key: str  # "openai-chat"
    media_type: str  # "text" | "image" | "video" | "audio"
    family: str  # "openai" | "google" | "newapi"
    display_name_key: str  # 前端 i18n key（dashboard ns）
    request_method: str  # "POST"
    request_path_template: str  # "/v1/chat/completions"，可含 {model} 等占位
    build_backend: Callable[
        [CustomProvider, str],
        CustomTextBackend | CustomImageBackend | CustomVideoBackend | CustomAudioBackend,
    ]
    image_capabilities: frozenset[ImageCapability] | None = None  # image 类才填，非 image 类省略
    # 参考生视频单镜头参考图上限；仅 video 类有意义。
    # 显式 int：原样下传作为硬约束（0 表示不接受参考图，executor 据此将 references 裁剪为 0 张）。
    # None：未声明 —— 一个 endpoint 多 model、容量不同时 endpoint 维度给不出准数，由 resolver
    # 调 video_caps_for_model 按 model_id 读取该 model 的真实上限。
    video_max_reference_images: int | None = None
    # 当 video_max_reference_images 为 None 时，resolver 用此纯函数按 model_id 读 backend 声明的
    # caps —— 不构造 SDK client、不查 provider 行。video_max_reference_images 为 int 时此字段应为
    # None（endpoint 维度已能给出硬上限）。二者对每个 video endpoint 恰填其一（见注册表末尾不变式）。
    video_caps_for_model: Callable[[str], VideoCapabilities] | None = None
    # 该 endpoint 的 delegate.generate() 是否真的读取 VideoGenerationRequest.end_image 并下传
    # 尾帧约束。仅 video 类有意义；False 时即便系统判定或用户覆盖把 last_frame 置为 True，执行层
    # 也会静默丢弃尾帧、按无约束生成——写入侧 last_frame 覆盖据此收窄可开启的 endpoint 范围。
    end_image_capable: bool = False
    # 同构于 end_image_capable：该 endpoint 的 delegate.generate() 是否真的读取
    # VideoGenerationRequest.reference_audio_files 并组装进供应商请求。仅 video 类有意义；
    # False 时把 reference_audio_mode 覆盖为 direct 只会让能力声明失真，执行层照旧不带音色输入。
    reference_audio_capable: bool = False
    # 端点来源：``builtin`` = 随 Shotwise 发布、不可卸载；未来的端点市场安装条目写自己的来源
    # 标识。纯描述性元数据——它只回答「这条从哪来」，不承载安装 / 更新 / 卸载语义，也没有任何
    # 执行路径读它（见 docs/adr/0067-endpoint-marketplace-deferred.md）。
    source: str = "builtin"
    # 条目版本：内置端点随应用发布、无独立版本号，故为 None；市场安装的条目带自己的版本。
    version: str | None = None


class EndpointDeclarationValidationError(ValueError):
    """Raised when a declarative endpoint contains an unsafe or invalid value."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


@dataclass(frozen=True)
class EndpointPoll:
    """Declarative submit-and-poll transport for asynchronous custom endpoints."""

    path: str
    job_id: str
    status: str
    done_value: object
    failed_value: object | None
    result: str | None
    artifact_url: str | None
    headers: Mapping[str, str]
    interval_seconds: float
    timeout_seconds: float


@dataclass(frozen=True)
class EndpointDeclaration:
    """A deliberately small, data-only description of one custom endpoint."""

    method: str
    path: str
    headers: Mapping[str, str]
    body_mapping: Mapping[str, str]
    response_mapping: Mapping[str, str]
    capability_overrides: Mapping[str, object]
    body_template: Mapping[str, object] | None = None
    poll: EndpointPoll | None = None


@dataclass(frozen=True)
class RenderedEndpointRequest:
    """The safe request produced from an :class:`EndpointDeclaration`."""

    method: str
    path: str
    headers: dict[str, str]
    body: dict[str, object]


@dataclass(frozen=True)
class RenderedEndpointPoll:
    """The safe poll request produced from an :class:`EndpointDeclaration`."""

    path: str
    headers: dict[str, str]


def _poll_to_dict(poll: EndpointPoll | None) -> dict[str, object] | None:
    if poll is None:
        return None
    return {
        "path": poll.path,
        "job_id": poll.job_id,
        "status": poll.status,
        "done_value": poll.done_value,
        "failed_value": poll.failed_value,
        "result": poll.result,
        "artifact_url": poll.artifact_url,
        "headers": dict(poll.headers),
        "interval_seconds": poll.interval_seconds,
        "timeout_seconds": poll.timeout_seconds,
    }


def endpoint_declaration_to_dict(declaration: EndpointDeclaration | None) -> dict[str, object] | None:
    """Return the JSON-safe representation used by the custom-provider API and DB."""
    if declaration is None:
        return None
    validate_endpoint_declaration(declaration)
    result: dict[str, object] = {
        "method": declaration.method,
        "path": declaration.path,
        "headers": dict(declaration.headers),
        "body": dict(declaration.body_mapping),
        "response": dict(declaration.response_mapping),
        "capability_overrides": dict(declaration.capability_overrides),
    }
    if declaration.body_template is not None:
        result["body_template"] = declaration.body_template
    if declaration.poll is not None:
        result["poll"] = _poll_to_dict(declaration.poll)
    return result


_DECLARATION_FIELDS = frozenset(
    {"method", "path", "headers", "body", "body_template", "response", "capability_overrides", "poll"}
)
_DECLARATION_METHODS = frozenset({"POST"})
_DECLARATION_HEADERS = {"accept": "Accept", "content-type": "Content-Type"}
_SIMPLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_PATH_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_TEMPLATE_PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_-]*)\}")
_JSON_POINTER_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_JSON_POINTER_INDEX = re.compile(r"^(0|[1-9][0-9]*)$")
_POLL_FIELDS = frozenset(
    {
        "path",
        "job_id",
        "status",
        "done_value",
        "failed_value",
        "result",
        "artifact_url",
        "headers",
        "interval_seconds",
        "timeout_seconds",
    }
)
# 允许出现在 body_template 中的声明式输入名。模板只做 JSON 结构拼装，不接受任意表达式。
_BODY_TEMPLATE_INPUTS = frozenset(
    {
        "model",
        "prompt",
        "system_prompt",
        "max_output_tokens",
        "aspect_ratio",
        "image_size",
        "seed",
        "reference_images",
        "text",
        "voice",
        "language_type",
        "speed",
        "duration",
        "duration_seconds",
        "resolution",
        "start_image",
        "end_image",
        "reference_audio_files",
        "generate_audio",
    }
)
_POLL_POINTER_PLACEHOLDERS = frozenset({"job_id", "model"})
_MAX_TEMPLATE_DEPTH = 32
_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DEFAULT_POLL_TIMEOUT_SECONDS = 300.0
_MIN_POLL_INTERVAL_SECONDS = 0.05
_MAX_POLL_INTERVAL_SECONDS = 60.0
_MAX_POLL_TIMEOUT_SECONDS = 3600.0


def _declaration_error(message: str, field: str) -> EndpointDeclarationValidationError:
    return EndpointDeclarationValidationError(f"{field}: {message}", field=field)


def _validate_path(
    path: object,
    *,
    field: str = "path",
    placeholders: frozenset[str] | None = frozenset({"model"}),
    allow_query: bool = False,
) -> str:
    if not isinstance(path, str) or not path:
        raise _declaration_error("must be a non-empty relative path", field)
    parsed = urlsplit(path)
    if (
        not path.startswith("/")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        raise _declaration_error("must be an absolute-path reference without a URL or query", field)
    if any(part == ".." for part in path.split("/")):
        raise _declaration_error("must not contain path traversal", field)
    for placeholder in _PATH_PLACEHOLDER.findall(path):
        if not _SIMPLE_NAME.fullmatch(placeholder):
            raise _declaration_error("placeholder names must be simple field names", field)
        if placeholders is not None and placeholder not in placeholders:
            allowed = ", ".join(f"{{{name}}}" for name in sorted(placeholders))
            raise _declaration_error(f"only the {allowed} placeholder(s) are allowed", field)
    return path


def _validate_object_pointer(
    pointer: object,
    *,
    field: str,
    allow_array: bool,
    placeholders: frozenset[str] = frozenset(),
) -> str:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise _declaration_error("must be a JSON Pointer-like path starting with '/'", field)
    tokens = pointer[1:].split("/")
    if not tokens or any(not token for token in tokens):
        raise _declaration_error("must not contain empty path components", field)
    for token in tokens:
        if re.search(r"~(?![01])", token):
            raise _declaration_error("contains an unsupported path component", field)
        decoded = token.replace("~1", "/").replace("~0", "~")
        placeholder_match = _TEMPLATE_PLACEHOLDER.fullmatch(decoded)
        if placeholder_match is not None:
            placeholder = placeholder_match.group(1)
            if placeholder not in placeholders:
                allowed = ", ".join(f"{{{name}}}" for name in sorted(placeholders)) or "none"
                raise _declaration_error(f"placeholder {{{placeholder}}} is not allowed; allowed: {allowed}", field)
            decoded = "job_id"
        if allow_array:
            if not (_JSON_POINTER_TOKEN.fullmatch(decoded) or _JSON_POINTER_INDEX.fullmatch(decoded)):
                raise _declaration_error("contains an unsupported response path component", field)
        elif not _JSON_POINTER_TOKEN.fullmatch(decoded):
            raise _declaration_error("body paths only support named object fields", field)
    return pointer


def _validate_headers(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise _declaration_error("must be an object", "header")
    headers: dict[str, str] = {}
    for name, value in raw.items():
        canonical_name = _DECLARATION_HEADERS.get(name.lower()) if isinstance(name, str) else None
        if canonical_name is None:
            raise _declaration_error(f"header {name!r} is not declared in the allowlist", "header")
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise _declaration_error("must be a static string without line breaks", "header")
        headers[canonical_name] = value
    return headers


def _validate_mapping(raw: object, *, field: str, response: bool) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise _declaration_error("must be an object", field)
    result: dict[str, str] = {}
    for key, value in raw.items():
        if response:
            if not isinstance(key, str) or not _SIMPLE_NAME.fullmatch(key):
                raise _declaration_error("response names must be simple field names", field)
            pointer = _validate_object_pointer(value, field=field, allow_array=True)
        else:
            pointer = _validate_object_pointer(key, field=field, allow_array=False)
            if not isinstance(value, str) or not _SIMPLE_NAME.fullmatch(value):
                raise _declaration_error("body values must be simple input names", field)
        if pointer in result.values():
            raise _declaration_error("contains duplicate mapping paths", field)
        result[str(key)] = pointer if response else str(value)

    if not response:
        paths = sorted(result)
        if any(child.startswith(parent + "/") for parent in paths for child in paths if child != parent):
            raise _declaration_error("cannot map both a field and one of its children", field)
    return result


def _iter_template_placeholders(value: str, *, field: str) -> list[str]:
    names: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "{":
            index += 1
            continue
        end = value.find("}", index + 1)
        if end == -1:
            raise _declaration_error("contains an unclosed template placeholder", field)
        name = value[index + 1 : end]
        if not _SIMPLE_NAME.fullmatch(name):
            raise _declaration_error("placeholder names must be simple field names", field)
        names.append(name)
        index = end + 1
    return names


def _validate_template(value: object, *, field: str, depth: int = 0) -> object:
    if depth > _MAX_TEMPLATE_DEPTH:
        raise _declaration_error("nesting is too deep", field)
    if isinstance(value, str):
        for name in _iter_template_placeholders(value, field=field):
            if name not in _BODY_TEMPLATE_INPUTS:
                raise _declaration_error(f"placeholder {{{name}}} is not an allowed input", field)
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise _declaration_error("object keys must be non-empty strings", field)
            result[key] = _validate_template(item, field=field, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_validate_template(item, field=field, depth=depth + 1) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    raise _declaration_error("must contain only JSON-compatible values", field)


def _validate_scalar(value: object, *, field: str) -> object:
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    raise _declaration_error("must be a scalar JSON value", field)


def _validate_poll(raw: object) -> EndpointPoll | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _declaration_error("must be an object", "poll")
    unknown = set(raw) - _POLL_FIELDS
    if unknown:
        raise _declaration_error(f"unknown fields: {sorted(unknown)!r}", "poll")
    path = _validate_path(raw.get("path"), field="poll.path", placeholders=frozenset({"model", "job_id"}))
    job_id = _validate_object_pointer(
        raw.get("job_id"), field="poll.job_id", allow_array=True, placeholders=_POLL_POINTER_PLACEHOLDERS
    )
    status = _validate_object_pointer(
        raw.get("status"), field="poll.status", allow_array=True, placeholders=_POLL_POINTER_PLACEHOLDERS
    )
    done_value = _validate_scalar(raw.get("done_value"), field="poll.done_value")
    # done 哨兵必须显式给出：缺省为 None 时，取不到状态（含状态指针缺失）的轮询响应会命中
    # `status == None`，把未完成任务误判为已完成。
    if done_value is None:
        raise _declaration_error("is required and must not be null", "poll.done_value")
    failed_value = _validate_scalar(raw.get("failed_value"), field="poll.failed_value")
    result_raw = raw.get("result")
    result = (
        None
        if result_raw is None
        else _validate_object_pointer(
            result_raw, field="poll.result", allow_array=True, placeholders=_POLL_POINTER_PLACEHOLDERS
        )
    )
    artifact_url_raw = raw.get("artifact_url")
    artifact_url = (
        None
        if artifact_url_raw is None
        else _validate_path(artifact_url_raw, field="poll.artifact_url", placeholders=None, allow_query=True)
    )
    headers = _validate_headers(raw.get("headers", {}))
    interval = raw.get("interval_seconds", _DEFAULT_POLL_INTERVAL_SECONDS)
    timeout = raw.get("timeout_seconds", _DEFAULT_POLL_TIMEOUT_SECONDS)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise _declaration_error("must be a number", "poll.interval_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise _declaration_error("must be a number", "poll.timeout_seconds")
    interval_seconds = float(interval)
    timeout_seconds = float(timeout)
    if not _MIN_POLL_INTERVAL_SECONDS <= interval_seconds <= _MAX_POLL_INTERVAL_SECONDS:
        raise _declaration_error(
            f"must be between {_MIN_POLL_INTERVAL_SECONDS} and {_MAX_POLL_INTERVAL_SECONDS} seconds",
            "poll.interval_seconds",
        )
    if not interval_seconds <= timeout_seconds <= _MAX_POLL_TIMEOUT_SECONDS:
        raise _declaration_error(
            f"must be between the poll interval and {_MAX_POLL_TIMEOUT_SECONDS} seconds", "poll.timeout_seconds"
        )
    return EndpointPoll(
        path=path,
        job_id=job_id,
        status=status,
        done_value=done_value,
        failed_value=failed_value,
        result=result,
        artifact_url=artifact_url,
        headers=headers,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
    )


def validate_endpoint_declaration(declaration: EndpointDeclaration) -> EndpointDeclaration:
    """Validate an already parsed declaration and return it unchanged."""
    if not isinstance(declaration, EndpointDeclaration):
        raise _declaration_error("must be an EndpointDeclaration", "declaration")
    if declaration.method not in _DECLARATION_METHODS:
        raise _declaration_error(f"method {declaration.method!r} is not allowed", "method")
    _validate_path(declaration.path)
    _validate_headers(declaration.headers)
    _validate_mapping(declaration.body_mapping, field="body", response=False)
    _validate_mapping(declaration.response_mapping, field="response", response=True)
    if declaration.body_mapping and declaration.body_template is not None:
        raise _declaration_error("body and body_template are mutually exclusive", "body_template")
    if declaration.body_template is not None:
        if not isinstance(declaration.body_template, Mapping):
            raise _declaration_error("must be an object", "body_template")
        _validate_template(declaration.body_template, field="body_template")
    if declaration.poll is not None:
        if not isinstance(declaration.poll, EndpointPoll):
            raise _declaration_error("must be an EndpointPoll", "poll")
        _validate_poll(_poll_to_dict(declaration.poll))
    if not isinstance(declaration.capability_overrides, Mapping):
        raise _declaration_error("must be an object", "capability_overrides")
    for key, value in declaration.capability_overrides.items():
        if not isinstance(key, str) or not _SIMPLE_NAME.fullmatch(key):
            raise _declaration_error("capability names must be simple field names", "capability_overrides")
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise _declaration_error("values must be scalar JSON values", "capability_overrides")
    return declaration


def parse_endpoint_declaration(raw: object) -> EndpointDeclaration:
    """Parse and validate a data-only endpoint declaration."""
    if not isinstance(raw, Mapping):
        raise _declaration_error("must be an object", "declaration")
    unknown = set(raw) - _DECLARATION_FIELDS
    if unknown:
        raise _declaration_error(f"unknown fields: {sorted(unknown)!r}", "declaration")
    method = raw.get("method", "POST")
    if not isinstance(method, str):
        raise _declaration_error("must be a string", "method")
    method = method.upper()
    if method not in _DECLARATION_METHODS:
        raise _declaration_error(f"method {method!r} is not allowed", "method")
    path = _validate_path(raw.get("path"))
    body_raw = raw.get("body", {})
    body_template_raw = raw.get("body_template")
    if body_raw and body_template_raw is not None:
        raise _declaration_error("body and body_template are mutually exclusive", "body_template")
    if body_template_raw is not None:
        if not isinstance(body_template_raw, Mapping):
            raise _declaration_error("must be an object", "body_template")
        _validate_template(body_template_raw, field="body_template")

    declaration = EndpointDeclaration(
        method=method,
        path=path,
        headers=_validate_headers(raw.get("headers", {})),
        body_mapping=_validate_mapping(body_raw, field="body", response=False),
        response_mapping=_validate_mapping(raw.get("response", {}), field="response", response=True),
        capability_overrides=dict(raw.get("capability_overrides", {}))
        if isinstance(raw.get("capability_overrides", {}), Mapping)
        else {},
        body_template=dict(body_template_raw) if isinstance(body_template_raw, Mapping) else None,
        poll=_validate_poll(raw.get("poll")),
    )
    if "capability_overrides" in raw and not isinstance(raw["capability_overrides"], Mapping):
        raise _declaration_error("must be an object", "capability_overrides")
    return validate_endpoint_declaration(declaration)


def _render_path(path: str, inputs: Mapping[str, object], *, allowed: frozenset[str], allow_empty: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in allowed:
            raise _declaration_error(f"placeholder {{{name}}} is not allowed", "path")
        value = inputs.get(name)
        if not isinstance(value, str) or (not value and not allow_empty):
            raise _declaration_error(f"missing non-empty {name} value", "input")
        return quote(value, safe="-._~")

    return _PATH_PLACEHOLDER.sub(replace, path)


def _render_template(value: object, inputs: Mapping[str, object], *, depth: int = 0) -> object:
    if depth > _MAX_TEMPLATE_DEPTH:
        raise _declaration_error("nesting is too deep", "body_template")
    if isinstance(value, str):
        whole = _TEMPLATE_PLACEHOLDER.fullmatch(value)
        if whole is not None:
            name = whole.group(1)
            if name not in inputs:
                raise _declaration_error(f"missing input {name!r}", "input")
            return inputs[name]

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in inputs:
                raise _declaration_error(f"missing input {name!r}", "input")
            item = inputs[name]
            if isinstance(item, (Mapping, list)) or item is None:
                raise _declaration_error(f"input {name!r} must be a scalar for inline interpolation", "input")
            return str(item)

        return _TEMPLATE_PLACEHOLDER.sub(replace, value)
    if isinstance(value, Mapping):
        return {str(key): _render_template(item, inputs, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template(item, inputs, depth=depth + 1) for item in value]
    return value


def _set_body_value(body: dict[str, object], pointer: str, value: object) -> None:
    current = body
    tokens = [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]
    for token in tokens[:-1]:
        child = current.get(token)
        if child is None:
            child = {}
            current[token] = child
        if not isinstance(child, dict):
            raise _declaration_error("body path collides with a scalar", "body")
        current = child
    current[tokens[-1]] = value


def render_endpoint_declaration(
    declaration: EndpointDeclaration, inputs: Mapping[str, object], runtime_headers: Mapping[str, str] | None = None
) -> RenderedEndpointRequest:
    """Render a request using only fields explicitly declared by the endpoint."""
    validate_endpoint_declaration(declaration)
    if not isinstance(inputs, Mapping):
        raise _declaration_error("must be an object", "input")
    if runtime_headers or "headers" in inputs:
        raise _declaration_error("runtime headers are not permitted", "header")
    body: dict[str, object] = {}
    if declaration.body_template is not None:
        rendered = _render_template(declaration.body_template, inputs)
        if not isinstance(rendered, dict):
            raise _declaration_error("must render to a JSON object", "body_template")
        body = rendered
    else:
        for pointer, input_name in declaration.body_mapping.items():
            if input_name not in inputs:
                raise _declaration_error(f"missing input {input_name!r}", "input")
            _set_body_value(body, pointer, inputs[input_name])
    return RenderedEndpointRequest(
        method=declaration.method,
        path=_render_path(declaration.path, inputs, allowed=frozenset({"model"})),
        headers=dict(declaration.headers),
        body=body,
    )


def render_endpoint_poll(declaration: EndpointDeclaration, inputs: Mapping[str, object]) -> RenderedEndpointPoll | None:
    """Render the declared poll path and headers, if the endpoint declares polling."""
    validate_endpoint_declaration(declaration)
    if declaration.poll is None:
        return None
    return RenderedEndpointPoll(
        path=_render_path(declaration.poll.path, inputs, allowed=frozenset({"model", "job_id"})),
        headers=dict(declaration.poll.headers),
    )


def render_poll_pointer(pointer: str, inputs: Mapping[str, object]) -> str:
    """Substitute allowed placeholders in a poll JSON pointer, escaping pointer tokens."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in _POLL_POINTER_PLACEHOLDERS:
            raise _declaration_error(f"placeholder {{{name}}} is not allowed", "poll")
        value = inputs.get(name)
        if not isinstance(value, str) or not value:
            raise _declaration_error(f"missing non-empty {name} value", "input")
        return value.replace("~", "~0").replace("/", "~1")

    return _TEMPLATE_PLACEHOLDER.sub(replace, pointer)


def get_json_pointer(document: object, pointer: str) -> object:
    """Read a JSON Pointer-like path from a provider document."""
    return _pointer_get(document, pointer)


def render_endpoint_artifact_url(poll: EndpointPoll, result: object) -> str | None:
    """Render the artifact URL template from a completed poll result."""
    if poll.artifact_url is None:
        return None
    inputs: dict[str, object] = {}
    if isinstance(result, Mapping):
        inputs.update({str(key): value for key, value in result.items()})
    elif isinstance(result, str):
        inputs["result"] = result

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = inputs.get(name)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise _declaration_error(f"artifact URL is missing scalar {name!r}", "poll.artifact_url")
        return quote(str(value), safe="-._~")

    return _TEMPLATE_PLACEHOLDER.sub(replace, poll.artifact_url)


def _pointer_get(document: object, pointer: str) -> object:
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list) and _JSON_POINTER_INDEX.fullmatch(token):
            index = int(token)
            if index >= len(current):
                raise IndexError(index)
            current = current[index]
        else:
            raise KeyError(token)
    return current


def normalize_endpoint_response(declaration: EndpointDeclaration, response: object) -> dict[str, object]:
    """Extract the declared response fields from a provider JSON document."""
    validate_endpoint_declaration(declaration)
    normalized: dict[str, object] = {}
    for name, pointer in declaration.response_mapping.items():
        try:
            normalized[name] = _pointer_get(response, pointer)
        except (IndexError, KeyError, TypeError) as exc:
            raise _declaration_error(f"missing response field at {pointer!r}", "response") from exc
    return normalized


# ── 各 endpoint 的 build_backend 闭包 ──────────────────────────────


def _build_openai_chat(provider, model_id: str) -> CustomTextBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    delegate = OpenAITextBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomTextBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_gemini_generate(provider, model_id: str) -> CustomTextBackend:
    base_url = ensure_google_base_url(provider.base_url) or None
    delegate = GeminiTextBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomTextBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


class _ImageTimeoutKwargs(TypedDict, total=False):
    timeout: float


def _image_request_timeout_kwargs(provider) -> _ImageTimeoutKwargs:
    """按「供应商列 > 环境变量 > backend 内置默认」透传图片请求超时。

    列值为 NULL 时返回空 dict（不下传 timeout），把「未设置」如实交给 backend 解析环境变量兜底——
    在这一层填默认值会让全局 env 调参失效。显式传 None 同样会覆盖 env，因此须整键省略。
    """
    timeout = getattr(provider, "image_request_timeout_seconds", None)
    return {"timeout": timeout} if timeout is not None else {}


def _build_openai_images(provider, model_id: str) -> CustomImageBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    delegate = OpenAIImageBackend(
        api_key=provider.api_key,
        base_url=base_url,
        model=model_id,
        **_image_request_timeout_kwargs(provider),
    )
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_openai_images_generations(provider, model_id: str) -> CustomImageBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    delegate = OpenAIImageBackend(
        api_key=provider.api_key,
        base_url=base_url,
        model=model_id,
        mode="generations_only",
        **_image_request_timeout_kwargs(provider),
    )
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_openai_images_edits(provider, model_id: str) -> CustomImageBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    delegate = OpenAIImageBackend(
        api_key=provider.api_key,
        base_url=base_url,
        model=model_id,
        mode="edits_only",
        **_image_request_timeout_kwargs(provider),
    )
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_gemini_image(provider, model_id: str) -> CustomImageBackend:
    base_url = ensure_google_base_url(provider.base_url) or None
    delegate = GeminiImageBackend(api_key=provider.api_key, base_url=base_url, image_model=model_id)
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_openai_tts(provider, model_id: str) -> CustomAudioBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    # provider_name 让 delegate 日志与 AudioSynthesisResult.provider 归因到真实 provider，
    # 与包装层 .name 的记账身份一致，而非内置 openai。
    delegate = OpenAIAudioBackend(
        api_key=provider.api_key,
        base_url=base_url,
        model=model_id,
        provider_name=provider.provider_id,
    )
    return CustomAudioBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_openai_video(provider, model_id: str) -> CustomVideoBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    delegate = OpenAIVideoBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_newapi_video(provider, model_id: str) -> CustomVideoBackend:
    base_url = ensure_openai_base_url(provider.base_url)
    if not base_url:
        raise ValueError("NewAPI 视频后端需要 base_url")
    delegate = NewAPIVideoBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _ensure_url_path_suffix(base_url: str | None, suffix: str) -> str | None:
    """补全协议已知挂载路径（ark /api/v3、vidu /ent/v2、kling /v1）；
    已带对应协议路径则原样信任，避免重复叠加。供 ark/vidu/kling 闭包复用。

    纯域名（无 scheme，如 ``relay.example.com``）会被 urlsplit 整体当作 path，
    先补 ``https://`` 再判定，否则 host-only 配置既补不上协议也挂不上路径。
    """
    s = (base_url or "").strip().rstrip("/")
    if not s:
        return None
    normalized = s if "://" in s else f"https://{s}"
    if urlsplit(normalized).path.rstrip("/").endswith(suffix):
        return normalized
    return normalized + suffix


def _build_v2_video_generations(provider, model_id: str) -> CustomVideoBackend:
    if not provider.base_url:
        raise ValueError("v2-video-generations 端点需要 base_url")
    # base_url 归一化（去版本段 + 拼 /v2/video/generations）由 V2VideoGenerationsBackend 内部处理
    delegate = V2VideoGenerationsBackend(api_key=provider.api_key, base_url=provider.base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_ark_seedance(provider, model_id: str) -> CustomVideoBackend:
    base_url = _ensure_url_path_suffix(provider.base_url, "/api/v3")
    delegate = ArkVideoBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_vidu_video(provider, model_id: str) -> CustomVideoBackend:
    base_url = _ensure_url_path_suffix(provider.base_url, "/ent/v2")
    delegate = ViduVideoBackend(api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_dashscope_image(provider, model_id: str) -> CustomImageBackend:
    # backend 内部由 host 派生 /api/v1（容忍带/不带后缀），此处传原始 base_url 即可，不重复归一化
    delegate = DashScopeImageBackend(api_key=provider.api_key, base_url=provider.base_url, model=model_id)
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_dashscope_async_video(provider, model_id: str) -> CustomVideoBackend:
    delegate = DashScopeVideoBackend(api_key=provider.api_key, base_url=provider.base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_minimax_image(provider, model_id: str) -> CustomImageBackend:
    # backend 内部把 base_url 归一化为 {host}/v1（容忍 host 或带 /v1 后缀），此处传原始 base_url 即可
    delegate = MiniMaxImageBackend(api_key=provider.api_key, base_url=provider.base_url, model=model_id)
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_minimax_video(provider, model_id: str) -> CustomVideoBackend:
    # 两步取 URL（submit→轮询 file_id→retrieve download_url）由 MiniMaxVideoBackend 内部处理
    delegate = MiniMaxVideoBackend(api_key=provider.api_key, base_url=provider.base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_kling_image(provider, model_id: str) -> CustomImageBackend:
    # 中转站「原样代理可灵」：bearer 模式旁路 JWT 管理器，用静态 api_key 直发可灵原生异步图像端点。
    # 仅 host 时补全可灵协议挂载路径 /v1（含显式路径则原样信任）；原生 model_name 透传不解耦别名。
    base_url = _ensure_url_path_suffix(provider.base_url, "/v1")
    delegate = KlingImageBackend(auth_mode="bearer", api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomImageBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


def _build_kling_video(provider, model_id: str) -> CustomVideoBackend:
    # 中转站「原样代理可灵」：bearer 模式旁路 JWT 管理器，用静态 api_key 直发可灵原生异步视频端点。
    base_url = _ensure_url_path_suffix(provider.base_url, "/v1")
    delegate = KlingVideoBackend(auth_mode="bearer", api_key=provider.api_key, base_url=base_url, model=model_id)
    return CustomVideoBackend(provider_id=provider.provider_id, delegate=delegate, model=model_id)


# ── ENDPOINT_REGISTRY 注册表 ───────────────────────────────────────


ENDPOINT_REGISTRY: dict[str, EndpointSpec] = {
    "openai-chat": EndpointSpec(
        key="openai-chat",
        media_type="text",
        family="openai",
        display_name_key="endpoint_openai_chat_display",
        request_method="POST",
        request_path_template="/v1/chat/completions",
        build_backend=_build_openai_chat,
    ),
    "gemini-generate": EndpointSpec(
        key="gemini-generate",
        media_type="text",
        family="google",
        display_name_key="endpoint_gemini_generate_display",
        request_method="POST",
        request_path_template="/v1beta/models/{model}:generateContent",
        build_backend=_build_gemini_generate,
    ),
    "openai-images": EndpointSpec(
        key="openai-images",
        media_type="image",
        family="openai",
        display_name_key="endpoint_openai_images_display",
        request_method="POST",
        # /generations 与 /edits 由是否传参考图自动派发，brace 表达两条路径
        request_path_template="/v1/images/{generations,edits}",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_openai_images,
    ),
    "openai-images-generations": EndpointSpec(
        key="openai-images-generations",
        media_type="image",
        family="openai",
        display_name_key="endpoint_openai_images_generations_display",
        request_method="POST",
        request_path_template="/v1/images/generations",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE}),
        build_backend=_build_openai_images_generations,
    ),
    "openai-images-edits": EndpointSpec(
        key="openai-images-edits",
        media_type="image",
        family="openai",
        display_name_key="endpoint_openai_images_edits_display",
        request_method="POST",
        request_path_template="/v1/images/edits",
        image_capabilities=frozenset({ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_openai_images_edits,
    ),
    "gemini-image": EndpointSpec(
        key="gemini-image",
        media_type="image",
        family="google",
        display_name_key="endpoint_gemini_image_display",
        request_method="POST",
        request_path_template="/v1beta/models/{model}:generateContent",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_gemini_image,
    ),
    "openai-video": EndpointSpec(
        key="openai-video",
        media_type="video",
        family="openai",
        display_name_key="endpoint_openai_video_display",
        request_method="POST",
        request_path_template="/v1/videos",
        build_backend=_build_openai_video,
        # OpenAI Sora input_reference 为单张首帧图。
        video_max_reference_images=1,
    ),
    "newapi-video": EndpointSpec(
        key="newapi-video",
        media_type="video",
        family="newapi",
        display_name_key="endpoint_newapi_video_display",
        request_method="POST",
        request_path_template="/v1/video/generations",
        build_backend=_build_newapi_video,
        video_max_reference_images=0,
    ),
    "v2-video-generations": EndpointSpec(
        key="v2-video-generations",
        media_type="video",
        family="v2",
        display_name_key="endpoint_v2_video_generations_display",
        request_method="POST",
        request_path_template="/v2/video/generations",
        build_backend=_build_v2_video_generations,
        # 多 model 共享端点、容量不同 → endpoint 维度不声明，按 model 读 backend caps（不构造 client）
        video_caps_for_model=V2VideoGenerationsBackend.video_capabilities_for_model,
        end_image_capable=True,
    ),
    "ark-seedance": EndpointSpec(
        key="ark-seedance",
        media_type="video",
        family="ark",
        display_name_key="endpoint_ark_seedance_display",
        request_method="POST",
        request_path_template="/api/v3/contents/generations/tasks",
        build_backend=_build_ark_seedance,
        video_caps_for_model=ArkVideoBackend.video_capabilities_for_model,
        end_image_capable=True,
        # _create_task 为 reference_audio_files 逐段组装 audio_url + role: reference_audio
        reference_audio_capable=True,
    ),
    "vidu-video": EndpointSpec(
        key="vidu-video",
        media_type="video",
        family="vidu",
        display_name_key="endpoint_vidu_video_display",
        request_method="POST",
        request_path_template="/ent/v2/img2video",
        build_backend=_build_vidu_video,
        video_caps_for_model=ViduVideoBackend.video_capabilities_for_model,
        end_image_capable=True,
    ),
    "dashscope-image": EndpointSpec(
        key="dashscope-image",
        media_type="image",
        family="dashscope",
        display_name_key="endpoint_dashscope_image_display",
        request_method="POST",
        request_path_template="/api/v1/services/aigc/multimodal-generation/generation",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_dashscope_image,
    ),
    "openai-tts": EndpointSpec(
        key="openai-tts",
        media_type="audio",
        family="openai",
        display_name_key="endpoint_openai_tts_display",
        request_method="POST",
        request_path_template="/v1/audio/speech",
        build_backend=_build_openai_tts,
    ),
    "dashscope-async-video": EndpointSpec(
        key="dashscope-async-video",
        media_type="video",
        family="dashscope",
        display_name_key="endpoint_dashscope_async_video_display",
        request_method="POST",
        request_path_template="/api/v1/services/aigc/video-generation/video-synthesis",
        build_backend=_build_dashscope_async_video,
        # 多 model（happyhorse-r2v=9 / wan2.7-r2v=5）容量不同 → endpoint 维度不声明 int cap，
        # 按 model 读 backend caps（不构造 client）。
        video_caps_for_model=DashScopeVideoBackend.video_capabilities_for_model,
        # _build_media 把 reference_audio_files 逐段挂到参考素材项的 reference_voice 上
        reference_audio_capable=True,
    ),
    "minimax-image": EndpointSpec(
        key="minimax-image",
        media_type="image",
        family="minimax",
        display_name_key="endpoint_minimax_image_display",
        request_method="POST",
        request_path_template="/image_generation",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_minimax_image,
    ),
    "minimax-video": EndpointSpec(
        key="minimax-video",
        media_type="video",
        family="minimax",
        display_name_key="endpoint_minimax_video_display",
        request_method="POST",
        request_path_template="/video_generation",
        build_backend=_build_minimax_video,
        # 多 model 容量异质（S2V-01 单脸参考 max_ref=1 / 海螺系列走首帧 no-ref）→ endpoint 维度不
        # 声明 int cap，按 model 读 backend caps（不构造 client）。
        video_caps_for_model=MiniMaxVideoBackend.video_capabilities_for_model,
    ),
    "kling-image": EndpointSpec(
        key="kling-image",
        media_type="image",
        family="kling",
        display_name_key="endpoint_kling_image_display",
        request_method="POST",
        request_path_template="/v1/images/generations",
        image_capabilities=frozenset({ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}),
        build_backend=_build_kling_image,
    ),
    "kling-video": EndpointSpec(
        key="kling-video",
        media_type="video",
        family="kling",
        display_name_key="endpoint_kling_video_display",
        request_method="POST",
        # 无首帧走 text2video、有首帧走 image2video（含可选尾帧）、有多图主体走 multi-image2video（R2V）
        request_path_template="/v1/videos/{text2video,image2video,multi-image2video}",
        build_backend=_build_kling_video,
        # 参考图上限随 model 异质（v3-omni / video-o1 多图主体 R2V max=4，其余首尾帧无参考为 0）→ 不在
        # endpoint 维度声明 int cap，按 model 读 backend 纯 caps 函数（与 minimax-video 同构）。
        video_caps_for_model=KlingVideoBackend.video_capabilities_for_model,
        end_image_capable=True,
    ),
}


ENDPOINT_KEYS_BY_MEDIA_TYPE: dict[str, tuple[str, ...]] = {
    media_type: tuple(k for k, s in ENDPOINT_REGISTRY.items() if s.media_type == media_type)
    for media_type in {s.media_type for s in ENDPOINT_REGISTRY.values()}
}


def _validate_video_caps_declarations() -> None:
    """import 期校验参考图上限来源：caps_fn 若声明必须可调用；每个 video endpoint 必须「int cap」
    XOR「caps_fn 非 None」恰一、且 int cap 非负；非 video endpoint 两者皆 None。misconfig（caps_fn
    填成非 callable、多 model 共享端点漏配 caps_fn、同时声明二者、或声明负数 cap）在 import 期
    fail-fast，而非等到 request 期 resolver 才抛。
    """
    for key, spec in ENDPOINT_REGISTRY.items():
        cap = spec.video_max_reference_images
        caps_fn = spec.video_caps_for_model
        has_int = cap is not None
        # resolver 会以 caps_fn(model_id) 执行它，故必须是 callable。误填字符串/整数等非空非 callable
        # 值要在 import 期就挡掉，而非放行到请求期才在 resolver 里炸——与本函数的 fail-fast 初衷一致。
        if caps_fn is not None and not callable(caps_fn):
            raise ValueError(f"endpoint {key!r} declares non-callable video_caps_for_model: {caps_fn!r}")
        has_fn = callable(caps_fn)
        if spec.media_type != "video" and spec.reference_audio_capable:
            raise ValueError(f"non-video endpoint {key!r} must not declare reference_audio_capable")
        if spec.media_type == "video":
            if has_int == has_fn:
                raise ValueError(
                    f"video endpoint {key!r} must declare exactly one of video_max_reference_images "
                    f"(int) or video_caps_for_model (callable), got "
                    f"video_max_reference_images={cap!r}, "
                    f"video_caps_for_model={caps_fn!r}"
                )
            if cap is not None and cap < 0:
                # int cap 是参考图张数硬上限；负数到了下游会被当负切片 references[:-1] 误丢最后一张
                # 而非裁成 0 张 → import 期挡掉，保证 resolver int 分支取到的恒为合法非负数。
                raise ValueError(f"video endpoint {key!r} declares negative video_max_reference_images: {cap}")
        elif has_int or has_fn:
            raise ValueError(
                f"non-video endpoint {key!r} must not declare video caps, got "
                f"video_max_reference_images={cap!r}, "
                f"video_caps_for_model={caps_fn!r}"
            )


_validate_video_caps_declarations()


# ── 工具函数 ───────────────────────────────────────────────────────


def get_endpoint_spec(endpoint: str) -> EndpointSpec:
    spec = ENDPOINT_REGISTRY.get(endpoint)
    if spec is None:
        raise ValueError(f"unknown endpoint: {endpoint!r}")
    return spec


def endpoint_to_media_type(endpoint: str) -> str:
    return get_endpoint_spec(endpoint).media_type


def endpoint_to_image_capabilities(endpoint: str) -> frozenset[ImageCapability]:
    """返回 image 类 endpoint 的 capability 集合。非 image 类抛 ValueError。"""
    spec = get_endpoint_spec(endpoint)
    if spec.image_capabilities is None:
        raise ValueError(f"endpoint {endpoint!r} is not an image endpoint")
    return spec.image_capabilities


def list_endpoints_by_media_type(media_type: str) -> list[EndpointSpec]:
    return [ENDPOINT_REGISTRY[k] for k in ENDPOINT_KEYS_BY_MEDIA_TYPE.get(media_type, ())]


def endpoint_spec_to_dict(spec: EndpointSpec) -> dict:
    """把 EndpointSpec 转成可序列化的纯数据 dict（剥掉不可 JSON 化的 build_backend 闭包）。"""
    data = asdict(spec)
    data.pop("build_backend", None)
    data.pop("video_caps_for_model", None)  # 同 build_backend：callable 不可 JSON 化，剥掉
    if spec.image_capabilities is not None:
        data["image_capabilities"] = sorted(c.value for c in spec.image_capabilities)
    else:
        data["image_capabilities"] = None
    return data


# ── 启发式：从 model_id + discovery_format 推默认 endpoint ─────────


_IMAGE_PATTERN = re.compile(r"image|dall|img|imagen|flux|seedream|jimeng|viduq[12](?:[-_].*)?", re.IGNORECASE)
_VIDEO_PATTERN = re.compile(
    r"video|sora|kling|wan|seedance|cog|mochi|veo|pika|runway|"
    r"vidu2(?:\.0)?(?:[-_].*)?|viduq3(?:[-_].*)?",
    re.IGNORECASE,
)
# TTS 模型 id 识别（tts-1 / gpt-4o-mini-tts / speech-1.5 / cosyvoice 等）。
# 刻意不含裸 "audio"：gpt-4o-audio-preview 等 chat 音频模态模型会被误归 TTS。
_AUDIO_PATTERN = re.compile(r"tts|speech|cosyvoice", re.IGNORECASE)
# 裸 "speech" 会撞上 ASR（语音转文字）家族 id，按内容排除，避免把识别模型默认归到 TTS 端点
_ASR_PATTERN = re.compile(r"transcribe|speech.?to.?text|recognition", re.IGNORECASE)


def infer_endpoint(model_id: str, discovery_format: str) -> str:
    """根据模型 id 与 discovery_format 推默认 endpoint（content-first）。

    model id 内容优先于 discovery_format：中转站普遍 discovery_format="openai"，但模型
    列表常夹带 gemini-*/imagen-* 原生 id，必须按内容纠偏到 Google 端点，否则被错推到
    openai-chat/openai-images，每次都要手动改回。

    1) 阿里百炼视频 → happyhorse / wan2.x / wan3.0（非 image）走 "dashscope-async-video"（原生异步
       端点）。happyhorse 不在 _VIDEO_PATTERN 须显式；wan2.x / wan3.0 视频抢在通用 is_video 前拦截。
       图像不自动推 dashscope（中转可能是 OpenAI 兼容），qwen-image / wan2.x-image / wan3.0-video-image
       落到既有图像家族推断。
    2) MiniMax 原生 token → 海螺 / S2V 走 "minimax-video"，image-01 走 "minimax-image"。先于通用
       is_video/is_image 拦截：s2v 不在 _VIDEO_PATTERN、image-01 含 "image" 否则会被推到通用图像家族。
    2.5) 可灵 kling token → 含 video 语义优先归 "kling-video"（kling-image2video 等 i2v 含 image
       语义但本质是视频）；其余含 image 语义走 "kling-image"，否则走 "kling-video"。kling 同时命中
       _VIDEO_PATTERN，须先于通用 is_video 拦截，否则视频会落到 openai-video；v3-omni 图像/视频同名
       默认归视频、图像手动选。
    3) imagen → "gemini-image"（图像，不论 discovery_format）
    4) gemini 原生模型（非 video）→ image 形态走 "gemini-image"，否则文本走 "gemini-generate"
    5) 视频家族 → seedance→"ark-seedance"、viduq3→"vidu-video"、否则 "openai-video"
    6) 图像家族 → discovery_format=google 走 "gemini-image" 否则 "openai-images"
    7) TTS 家族（tts/speech/cosyvoice）→ "openai-tts"（audio 仅 OpenAI 兼容一条端点，
       不分 discovery_format；precedence 在 text 默认之前）
    8) 默认（文本）→ discovery_format=google 走 "gemini-generate" 否则 "openai-chat"
    """
    lowered = model_id.lower()
    is_image = bool(_IMAGE_PATTERN.search(model_id))
    # 万相带版本号的 id（视频与图像变体都含该 token），下面路由与 is_video 排除各用一次
    is_wan_versioned = "wan2." in lowered or "wan3." in lowered

    # 阿里百炼视频先于通用 is_video 拦截到原生异步端点
    if "happyhorse" in lowered:
        return "dashscope-async-video"
    if is_wan_versioned and not is_image:
        return "dashscope-async-video"

    # MiniMax 原生 token 二级路由：海螺（含 minimax-hailuo）/ S2V / H3 → 两步或单步取回的视频端点；
    # image-01 → 单步图像端点。先于通用 is_video/is_image：s2v 与 h3 均不被 _VIDEO_PATTERN 覆盖，
    # image-01 含 "image" 否则会被通用图像家族抢走。匹配 "minimax-h3" 而非裸 "h3"——后者过短，
    # 容易撞上其它厂商恰好含 h3 子串的型号 id。
    if "hailuo" in lowered or "s2v" in lowered or "minimax-h3" in lowered:
        return "minimax-video"
    if "image-01" in lowered:
        return "minimax-image"

    # 可灵原生中转二级路由：kling 同时命中 _VIDEO_PATTERN（含 kling）与（含 image 语义时）
    # _IMAGE_PATTERN，须在通用 is_video/is_image 之前显式分流。video 语义优先于 image——
    # kling-image2video / kling-img2video 这类 image-to-video 含 image 语义但本质是视频模型，
    # 若直接看 is_image 会被误推到 kling-image，故先拦 video 关键字归 kling-video；其余含 image
    # 语义 → kling-image，否则 → kling-video。kling-v3-omni 图像/视频同名歧义无法纯靠 token 区分，
    # 默认归视频、图像手动选；不分 discovery_format（可灵端点各自唯一）。
    if "kling" in lowered:
        if "video" in lowered:
            return "kling-video"
        return "kling-image" if is_image else "kling-video"

    # wan2.x-image / wan3.0-video-image 含 "wan" 会被 _VIDEO_PATTERN 误判为视频；显式排除让它落到
    # 图像家族推断
    is_video = bool(_VIDEO_PATTERN.search(model_id)) and not (is_wan_versioned and is_image)

    if "imagen" in lowered:
        return "gemini-image"
    if "gemini" in lowered and not is_video:
        return "gemini-image" if is_image else "gemini-generate"
    if is_video:
        if "seedance" in lowered:
            return "ark-seedance"
        if "viduq3" in lowered:
            return "vidu-video"
        return "openai-video"
    if is_image:
        return "gemini-image" if discovery_format == "google" else "openai-images"
    if _AUDIO_PATTERN.search(model_id) and not _ASR_PATTERN.search(model_id):
        return "openai-tts"
    return "gemini-generate" if discovery_format == "google" else "openai-chat"
