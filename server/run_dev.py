"""开发服务器启动入口。

Windows + Python 3.14 下，uvicorn reload 与 ProactorEventLoop 组合会在注册监听
socket 时触发 ``WinError 87``，导致进程虽然打印 startup complete，却无法接受
HTTP 请求。Windows 开发环境因此禁用 reload，保留 ProactorEventLoop 以支持
Claude Agent SDK、ffmpeg 等子进程；非 Windows 仍使用 reload。

用法（所有平台通用）：
    uv run python server/run_dev.py

可通过 ``LISTEN_HOST`` / ``LISTEN_PORT`` 覆盖默认监听地址和端口，例如：
    $env:LISTEN_PORT = "18080"; uv run python server/run_dev.py
"""

from __future__ import annotations

import os
import sys

from server._win_loop_patch import patch_windows_uvicorn_event_loop

# 必须放在模块顶层（而非 __main__ 块内）：spawn 的 reload worker 以 __mp_main__
# 重新执行本文件时也会走到这里，patch 先于 uvicorn 的 loop factory 装配。
patch_windows_uvicorn_event_loop()

if __name__ == "__main__":
    import uvicorn

    configured_port = os.environ.get("LISTEN_PORT")
    # 1241 is reserved by Windows on this machine; ignore stale shell settings.
    listen_port = int(configured_port) if configured_port and configured_port != "1241" else 18080
    reload_enabled = sys.platform != "win32"
    uvicorn.run(
        "server.app:app",
        host=os.environ.get("LISTEN_HOST") or "127.0.0.1",
        port=listen_port,
        reload=reload_enabled,
        reload_dirs=["server", "lib"] if reload_enabled else None,
    )
