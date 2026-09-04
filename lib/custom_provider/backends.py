"""自定义供应商 Backend 包装类。

将已有后端（OpenAI/Gemini 等）包装为自定义供应商，覆盖 name 和 model 属性。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import httpx

from lib.audio_backends.base import (
    AudioBackend,
    AudioCapability,
    AudioSynthesisRequest,
    AudioSynthesisResult,
    VoiceOption,
)
from lib.image_backends.base import ImageBackend, ImageCapability, ImageGenerationRequest, ImageGenerationResult
from lib.text_backends.base import TextBackend, TextCapability, TextGenerationRequest, TextGenerationResult
from lib.video_backends.base import (
    VideoBackend,
    VideoCapabilities,
    VideoGenerationRequest,
    VideoGenerationResult,
    download_video,
)


def _declarative_url(base_url: str, path: str) -> str:
    """Join a validated relative declaration path to the configured provider origin."""
    return base_url.rstrip("/") + path


async def _post_declarative(
    *,
    base_url: str,
    api_key: str,
    declaration,
    model: str,
    inputs: Mapping[str, object],
) -> dict[str, object]:
    from lib.custom_provider.endpoints import normalize_endpoint_response, render_endpoint_declaration

    rendered = render_endpoint_declaration(declaration, inputs)
    headers = dict(rendered.headers)
    headers.setdefault("Authorization", f"Bearer {api_key}")
    async with httpx.AsyncClient() as client:
        response = await client.request(
            rendered.method,
            _declarative_url(base_url, rendered.path),
            headers=headers,
            json=rendered.body,
            timeout=120,
        )
    response.raise_for_status()
    try:
        document = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"declarative endpoint returned non-JSON response for {model}") from exc
    return normalize_endpoint_response(declaration, document)


def _request_inputs(model: str, **values: object) -> dict[str, object]:
    inputs: dict[str, object] = {"model": model}
    for name, value in values.items():
        if isinstance(value, Path):
            inputs[name] = str(value)
        elif isinstance(value, list) and all(isinstance(item, Path) for item in value):
            inputs[name] = [str(item) for item in value]
        else:
            inputs[name] = value
    return inputs


def _response_value(response: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in response:
            return response[name]
    raise ValueError(f"declarative endpoint response must map one of {names!r}")


class DeclarativeTextDelegate:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, declaration) -> None:
        self._provider_id, self._base_url, self._api_key = provider_id, base_url, api_key
        self._model, self._declaration = model, declaration

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return {TextCapability.TEXT_GENERATION}

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        response = await _post_declarative(
            base_url=self._base_url,
            api_key=self._api_key,
            declaration=self._declaration,
            model=self._model,
            inputs=_request_inputs(
                self._model,
                prompt=request.prompt,
                system_prompt=request.system_prompt,
                max_output_tokens=request.max_output_tokens,
            ),
        )
        text = _response_value(response, "text", "content", "output")
        return TextGenerationResult(text=str(text), provider=self._provider_id, model=self._model)


class DeclarativeImageDelegate:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, declaration) -> None:
        self._provider_id, self._base_url, self._api_key = provider_id, base_url, api_key
        self._model, self._declaration = model, declaration

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[ImageCapability]:
        return {ImageCapability.TEXT_TO_IMAGE}

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        response = await _post_declarative(
            base_url=self._base_url,
            api_key=self._api_key,
            declaration=self._declaration,
            model=self._model,
            inputs=_request_inputs(
                self._model,
                prompt=request.prompt,
                aspect_ratio=request.aspect_ratio,
                image_size=request.image_size,
                seed=request.seed,
                reference_images=request.reference_images,
            ),
        )
        value = _response_value(response, "image_url", "result_url", "url", "image_base64", "b64_json")
        if isinstance(value, str) and value.startswith("data:"):
            value = value.split(",", 1)[-1]
        if isinstance(value, str) and not value.startswith("http"):
            content = base64.b64decode(value)
            await _write_bytes(request.output_path, content)
        else:
            from lib.image_backends.base import download_image_to_path

            await download_image_to_path(str(value), request.output_path)
        return ImageGenerationResult(
            image_path=request.output_path,
            provider=self._provider_id,
            model=self._model,
        )


class DeclarativeVideoDelegate:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, declaration) -> None:
        self._provider_id, self._base_url, self._api_key = provider_id, base_url, api_key
        self._model, self._declaration = model, declaration

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def video_capabilities(self) -> VideoCapabilities:
        return VideoCapabilities()

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        response = await _post_declarative(
            base_url=self._base_url,
            api_key=self._api_key,
            declaration=self._declaration,
            model=self._model,
            inputs=_request_inputs(
                self._model,
                prompt=request.prompt,
                duration=request.duration_seconds,
                duration_seconds=request.duration_seconds,
                aspect_ratio=request.aspect_ratio,
                resolution=request.resolution,
                start_image=request.start_image,
                end_image=request.end_image,
                reference_images=request.reference_images or [],
                reference_audio_files=request.reference_audio_files or [],
                generate_audio=request.generate_audio,
            ),
        )
        url = str(_response_value(response, "video_url", "result_url", "url"))
        await download_video(url, request.output_path)
        task_id = response.get("task_id") or response.get("job_id")
        return VideoGenerationResult(
            video_path=request.output_path,
            provider=self._provider_id,
            model=self._model,
            duration_seconds=request.duration_seconds,
            video_uri=url,
            task_id=str(task_id) if task_id is not None else None,
        )

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        raise NotImplementedError


class DeclarativeAudioDelegate:
    def __init__(self, *, provider_id: str, base_url: str, api_key: str, model: str, declaration) -> None:
        self._provider_id, self._base_url, self._api_key = provider_id, base_url, api_key
        self._model, self._declaration = model, declaration

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[AudioCapability]:
        return {AudioCapability.TEXT_TO_SPEECH}

    def list_voices(self) -> list[VoiceOption]:
        return []

    async def synthesize(self, request: AudioSynthesisRequest) -> AudioSynthesisResult:
        response = await _post_declarative(
            base_url=self._base_url,
            api_key=self._api_key,
            declaration=self._declaration,
            model=self._model,
            inputs=_request_inputs(
                self._model,
                text=request.text,
                voice=request.voice,
                language_type=request.language_type,
                speed=request.speed,
            ),
        )
        value = _response_value(response, "audio_url", "result_url", "url", "audio_base64", "b64_json")
        if isinstance(value, str) and value.startswith("http"):
            async with httpx.AsyncClient() as client:
                download = await client.get(value, timeout=120)
            download.raise_for_status()
            content = download.content
        else:
            if isinstance(value, str) and value.startswith("data:"):
                value = value.split(",", 1)[-1]
            content = base64.b64decode(str(value))
        await _write_bytes(request.output_path, content)
        return AudioSynthesisResult(
            provider=self._provider_id,
            model=self._model,
            characters=len(request.text),
            output_path=request.output_path,
        )


async def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class CustomTextBackend:
    """自定义供应商文本生成后端包装类。"""

    def __init__(self, *, provider_id: str, delegate: TextBackend, model: str) -> None:
        self._provider_id = provider_id
        self._delegate = delegate
        self._model = model

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return self._delegate.capabilities

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        return await self._delegate.generate(request)


class CustomImageBackend:
    """自定义供应商图片生成后端包装类。"""

    def __init__(self, *, provider_id: str, delegate: ImageBackend, model: str) -> None:
        self._provider_id = provider_id
        self._delegate = delegate
        self._model = model

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[ImageCapability]:
        return self._delegate.capabilities

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return await self._delegate.generate(request)


class CustomAudioBackend:
    """自定义供应商语音合成后端包装类。"""

    def __init__(self, *, provider_id: str, delegate: AudioBackend, model: str) -> None:
        self._provider_id = provider_id
        self._delegate = delegate
        self._model = model

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[AudioCapability]:
        return self._delegate.capabilities

    def list_voices(self) -> list[VoiceOption]:
        return self._delegate.list_voices()

    async def synthesize(self, request: AudioSynthesisRequest) -> AudioSynthesisResult:
        return await self._delegate.synthesize(request)


class CustomVideoBackend:
    """自定义供应商视频生成后端包装类。

    ``video_capabilities`` 可被工厂注入生效能力（系统判定 ⊕ 用户覆盖），此时不再转发被包装
    backend 的声明——后者只是系统判定的一个来源，用户覆盖必须能翻转执行层看到的能力。未注入
    时（endpoint 闭包直接构造）回落到转发。
    """

    def __init__(
        self,
        *,
        provider_id: str,
        delegate: VideoBackend,
        model: str,
        video_capabilities: VideoCapabilities | None = None,
        capability_overrides: dict[str, object] | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._delegate = delegate
        self._model = model
        self._video_capabilities = video_capabilities
        self._capability_overrides = capability_overrides or {}
        self._endpoint = endpoint

    @property
    def endpoint(self) -> str | None:
        """构造本 backend 所用的 endpoint（ENDPOINT_REGISTRY 键），由工厂注入。

        endpoint 决定协议，是 backend 构造的真正输入粒度；模型行的 endpoint 可在同媒体类型内
        被改写，故已提交任务的续跑须比对它而非只比对 provider/model（``docs/adr/0054``）。
        绕过工厂直接构造时为 None，此时续跑不比对、行为与未持久化 endpoint 的存量任务一致。
        """
        return self._endpoint

    def with_video_capabilities(
        self, capabilities: VideoCapabilities, *, overrides: dict[str, object] | None = None
    ) -> CustomVideoBackend:
        """返回注入生效能力的新实例（不就地改写，包装器保持构造后不可变）。

        ``overrides`` 是过滤后的稀疏用户覆盖（`filter_valid_overrides` 的返回值），供
        `video_capabilities_for_tier` 叠加到档位感知基底上；与 ``capabilities``（系统判定 ⊕
        覆盖的完整合成结果，供 context-free 的 `video_capabilities` 属性使用）分开传递——
        两者不能合一，否则档位查询会短路回完整合成结果，见 `video_capabilities_for_tier`。
        """
        return CustomVideoBackend(
            provider_id=self._provider_id,
            delegate=self._delegate,
            model=self._model,
            video_capabilities=capabilities,
            capability_overrides=overrides,
            endpoint=self._endpoint,
        )

    def with_endpoint(self, endpoint: str) -> CustomVideoBackend:
        """返回记住构造 endpoint 的新实例（不就地改写，包装器保持构造后不可变）。"""
        return CustomVideoBackend(
            provider_id=self._provider_id,
            delegate=self._delegate,
            model=self._model,
            video_capabilities=self._video_capabilities,
            capability_overrides=self._capability_overrides,
            endpoint=endpoint,
        )

    @property
    def name(self) -> str:
        return self._provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def video_capabilities(self) -> VideoCapabilities:
        if self._video_capabilities is not None:
            return self._video_capabilities
        return self._delegate.video_capabilities

    def video_capabilities_for_tier(self, service_tier: str, resolution: str | None = None) -> VideoCapabilities:
        """按请求档位收窄能力：以被包装 backend（如 Kling）的档位感知查询为基底——
        `getattr` 探测是否实现（与 `media_generator` 的探测方式一致），未实现则回落其
        context-free `video_capabilities`——再叠加稀疏用户覆盖（未覆盖字段跟随基底）。

        不能直接短路返回工厂注入的完整合成结果（`self._video_capabilities`）：那是用
        context-free 的系统判定算出的（对 Kling 等档位敏感 backend 而言是保守声明），工厂
        路径下该字段永远非 None，短路会让本方法在生产环境等价于未实现档位感知，
        Pro 档本可接受的尾帧被静默丢弃。
        """
        tier_aware = getattr(self._delegate, "video_capabilities_for_tier", None)
        base = (
            tier_aware(service_tier, resolution=resolution)
            if tier_aware is not None
            else self._delegate.video_capabilities
        )
        if self._capability_overrides:
            # 合并后不变式与 synthesize 同口径：本路径也是一次「基底 ⊕ 稀疏覆盖」合并，
            # 漏掉就会让档位查询产出 direct ⊕ 上限 0 这种合成侧已挡住的组合。
            from lib.custom_provider.capabilities import enforce_audio_capability_invariant, merge_overrides

            return enforce_audio_capability_invariant(
                merge_overrides(base, self._capability_overrides),
                endpoint=self._delegate.name,
                model_id=self._model,
            )
        return base

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        # 注入本次执行的 endpoint，让下游协议 backend 在 submit 后与 job_id 一并持久化——
        # 续跑据此判定协议是否已被换掉。replace 而非就地改写：request 由调用方持有，
        # 包装层不该留下副作用。
        if self._endpoint is not None:
            request = replace(request, execution_endpoint=self._endpoint)
        return await self._delegate.generate(request)

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        # 透传到下游 backend；下游不支持 resume 时抛 NotImplementedError，
        # 由 orphan handler 标 [resume_unsupported]
        return await self._delegate.resume_video(job_id, request)
