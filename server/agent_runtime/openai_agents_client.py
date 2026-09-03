"""OpenAIAgentsSessionClient：把 openai-agents 的 Agent + Runner 适配到 SessionActor 的鸭子协议。

SessionActor 要求的 client 协议（见 ``session_actor.py``）：
- ``async with client_factory() as client``（AsyncContextManager）
- ``await client.query(prompt, session_id=...)``（prompt: str | AsyncIterable[dict]）
- ``client.receive_response()`` → AsyncIterable[dict]（Anthropic 风格消息协议）
- ``await client.interrupt()``

本类内部：
- ``__aenter__`` 构造 ``Agent``（instructions=系统提示、tools=Shotwise 工具、
  model_provider=OpenAI 兼容 provider）。Agents SDK 进程内运行，无子进程，无需
  启动/关闭清理。
- ``query`` 调 ``Runner.run_streamed(agent, input, session=SQLiteSession, ...)``
  并派生后台 task 消费 ``stream_events()``，经 ``OpenAIAgentsTranslator`` 翻译
  成现有协议消息推入 outbox。
- ``receive_response`` 从 outbox 逐条产出（流终止 = 轮次结束）。
- ``interrupt`` 调 ``result.cancel()`` 中断当前 run。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

_EOS = object()  # outbox 终止哨兵


class OpenAIAgentsSessionClient:
    def __init__(
        self,
        *,
        provider: Any,
        model: str,
        system_prompt: str,
        session: Any,
        tools: list[Any],
        max_turns: int | None,
        on_message: Any = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt
        self._session = session
        self._tools = tools
        self._max_turns = max_turns
        self._on_message = on_message
        self._agent: Any = None
        self._run_config: Any = None
        self._translator: Any = None
        self._outbox: asyncio.Queue[Any] | None = None
        self._stream_task: asyncio.Task | None = None
        self._result: Any = None
        self._interrupted = False

    # ── AsyncContextManager ─────────────────────────────────────────

    async def __aenter__(self) -> OpenAIAgentsSessionClient:
        from agents import Agent, RunConfig

        self._agent = Agent(
            name="Shotwise",
            instructions=self._system_prompt,
            tools=self._tools,
        )
        self._run_config = RunConfig(
            model=self._model or None,
            model_provider=self._provider,
        )
        return self

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
            with _suppress(BaseException):
                await self._stream_task
            self._stream_task = None
        self._agent = None
        self._result = None

    # ── SessionActor 协议 ───────────────────────────────────────────

    async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None:
        from agents import Runner

        if self._agent is None:
            raise RuntimeError("OpenAIAgentsSessionClient.query called before __aenter__")
        run_input = await self._collect_input(prompt)
        self._interrupted = False
        self._translator = self._build_translator()
        self._result = Runner.run_streamed(
            self._agent,
            run_input,
            session=self._session,
            max_turns=self._max_turns,
            run_config=self._run_config,
        )
        self._outbox = asyncio.Queue()
        self._stream_task = asyncio.create_task(self._drain_stream(), name="agents-run-stream")

    def receive_response(self) -> AsyncIterator[dict[str, Any]]:
        """Async generator：逐条产出翻译后的消息，流终止即结束。"""

        async def _gen() -> AsyncIterator[dict[str, Any]]:
            outbox = self._outbox
            if outbox is None:
                return
            while True:
                item = await outbox.get()
                if item is _EOS:
                    return
                yield item

        return _gen()

    async def interrupt(self) -> None:
        """中断当前 run（无活跃 run 时无操作）。"""
        if self._result is None:
            return
        self._interrupted = True
        with _suppress(BaseException):
            self._result.cancel()

    # ── 内部 ────────────────────────────────────────────────────────

    def _build_translator(self) -> Any:
        from server.agent_runtime.openai_agents_translator import OpenAIAgentsTranslator

        return OpenAIAgentsTranslator(session_id=self._session.session_id, model=self._model or "")

    async def _collect_input(self, prompt: str | AsyncIterable[dict]) -> Any:
        """把 str 或现有协议的多模态 prompt（AsyncIterable[dict]）转成 Agents SDK RunInput。"""
        if isinstance(prompt, str):
            return prompt
        content: list[dict[str, Any]] = []
        async for message in prompt:
            blocks = message.get("message", {}).get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        content.append({"type": "input_text", "text": text})
                elif block_type == "image":
                    source = block.get("source") or {}
                    media_type = source.get("media_type") or "image/png"
                    data = source.get("data")
                    if isinstance(data, str) and data:
                        content.append({"type": "input_image", "image_url": f"data:{media_type};base64,{data}"})
        return [{"role": "user", "content": content}]

    async def _drain_stream(self) -> None:
        """消费 stream_events()，翻译后推入 outbox；结束时构造 result 并推 EOS。"""
        outbox = self._outbox
        if outbox is None:
            return
        try:
            async for event in self._result.stream_events():
                try:
                    messages = self._translator.feed(event)
                except Exception:
                    logger.exception("OpenAI Agents 事件翻译失败 type=%s", getattr(event, "type", "?"))
                    continue
                for message in messages:
                    await outbox.put(message)
                    if self._on_message is not None:
                        try:
                            self._on_message(message)
                        except Exception:
                            logger.exception("OpenAI Agents on_message 回调失败")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # stream_events 可能已经发出文本 delta，但在 message_output_item
            # 到达前断开。先把可见文本定型为普通 assistant 条目，避免下面的
            # error result 触发 entry pipeline 清理 draft 后用户看不到任何回复。
            flush_partial = getattr(self._translator, "flush_partial_assistant", None)
            if callable(flush_partial):
                try:
                    partial = flush_partial()
                except Exception:
                    logger.exception("OpenAI Agents 部分 assistant 消息定型失败")
                else:
                    if partial is not None:
                        await self._emit_message(outbox, partial)
            logger.error("OpenAI Agents run stream 异常: %s", exc)
            await outbox.put(
                self._build_result(
                    status="error",
                    error="provider_stream_interrupted",
                    error_detail=str(exc),
                )
            )
        else:
            if self._interrupted:
                status = "interrupted"
                error = None
            elif not self._translator.has_assistant_output:
                status = "error"
                error = "provider_empty_response"
            else:
                status = "completed"
                error = None
            await outbox.put(self._build_result(status=status, error=error))
        finally:
            await outbox.put(_EOS)

    async def _emit_message(self, outbox: asyncio.Queue[Any], message: Any) -> None:
        await outbox.put(message)
        if self._on_message is not None:
            try:
                self._on_message(message)
            except Exception:
                logger.exception("OpenAI Agents on_message 回调失败")

    def _build_result(
        self,
        *,
        status: str,
        error: str | None = None,
        error_detail: str | None = None,
    ) -> dict[str, Any]:
        usage: dict[str, Any] = {}
        if self._result is not None:
            ctx_usage = getattr(getattr(self._result, "context_wrapper", None), "usage", None)
            if ctx_usage is not None:
                usage = {
                    "input_tokens": int(getattr(ctx_usage, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(ctx_usage, "output_tokens", 0) or 0),
                }
        result: dict[str, Any] = {
            "type": "result",
            "session_status": status,
            "model": self._model or "",
            "usage": usage,
        }
        if error is not None:
            result["error"] = error
        if error_detail:
            result["error_detail"] = error_detail
        return result


def _suppress(*exc_types: type[BaseException]) -> Any:
    import contextlib

    return contextlib.suppress(*exc_types)
