"""Windows 下 uvicorn 事件循环修正。

uvicorn 在 ``use_subprocess=True``（--reload 或 --workers>1）时，Windows 上会把
事件循环退化为 ``SelectorEventLoop``（见 uvicorn.loops.asyncio.asyncio_loop_factory，
为规避 cpython#122240 的 Proactor 多进程问题）。Python 3.14 起 Windows 的
Selector 事件循环不再实现 ``_make_subprocess_transport``，任何
``asyncio.create_subprocess_exec``（Claude Agent SDK 启动 claude.exe、ffmpeg 等）
都会抛 ``NotImplementedError``，表现为 Agent 启动失败
（``CLIConnectionError: Failed to start Claude Code``）。

本模块把 uvicorn 的 loop factory 替换为始终返回 ``ProactorEventLoop`` ——
Windows 上唯一支持子进程的 asyncio 事件循环。patch 只对 win32 生效；
非 reload 模式 uvicorn 本来就用 Proactor，行为不变。

取舍说明：uvicorn 在 reload/多 worker 下有意用 SelectorEventLoop 规避
cpython#122240（Proactor 多进程下的句柄问题）；本 patch 绕过了该规避。
对开发场景（--reload 单 worker）无影响，Windows 多 worker 部署的稳定性
未在此验证——生产多 worker 建议在 Linux/macOS 容器中运行。

调用时机（两层）：
- ``server.run_dev.py`` 顶层：uvicorn.run() 之前执行，覆盖 reload 模式 —— uvicorn
  的 ``Server.run()`` 先 ``get_loop_factory()`` 再 ``config.load()``（import app），
  app 模块内的 patch 来不及生效；spawn 的 reload worker 会以 ``__mp_main__``
  重新执行本文件顶层代码，patch 在 worker 的 Server.run() 前同样生效。
- ``server.app`` 模块级：非 reload 场景的兜底。
"""

from __future__ import annotations

import asyncio
import sys


def patch_windows_uvicorn_event_loop() -> None:
    """把 uvicorn 的 loop factory 替换为返回 ``ProactorEventLoop``（仅 win32）。"""
    if sys.platform != "win32":
        return
    try:
        from uvicorn.loops import asyncio as uvicorn_asyncio_loops
        from uvicorn.loops import auto as uvicorn_auto_loops
    except ImportError:
        return

    def _proactor_loop_factory(use_subprocess: bool = False):  # noqa: ARG001
        return asyncio.ProactorEventLoop

    uvicorn_asyncio_loops.asyncio_loop_factory = _proactor_loop_factory
    # auto 在 Windows 无 uvloop 时延迟 import asyncio_loop_factory，同样拿到修正版
    uvicorn_auto_loops.auto_loop_factory = _proactor_loop_factory
