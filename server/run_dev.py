"""开发服务器启动入口。

Windows + Python 3.14 下，uvicorn --reload/多 worker 会先创建事件循环再加载 app，
并把事件循环退化为 SelectorEventLoop（不支持子进程），导致 Claude Agent 启动
claude.exe 时 NotImplementedError。本入口在 uvicorn.run() 之前应用
``server._win_loop_patch`` 的修正；spawn 的 reload worker 会以 ``__mp_main__``
重新执行本文件顶层代码（不含 ``__main__`` 块），patch 在 worker 的 Server.run()
之前同样生效。

用法（所有平台通用，等价于原 uvicorn 命令）：
    uv run python server/run_dev.py

可通过 ``LISTEN_HOST`` / ``LISTEN_PORT`` 覆盖默认监听地址和端口，例如：
    $env:LISTEN_PORT = "18080"; uv run python server/run_dev.py

等价命令：
    uv run uvicorn server.app:app --reload --reload-dir server --reload-dir lib --port 18080
"""

from __future__ import annotations

import os

from server._win_loop_patch import patch_windows_uvicorn_event_loop

# 必须放在模块顶层（而非 __main__ 块内）：spawn 的 reload worker 以 __mp_main__
# 重新执行本文件时也会走到这里，patch 先于 uvicorn 的 loop factory 装配。
patch_windows_uvicorn_event_loop()

if __name__ == "__main__":
    import uvicorn

    configured_port = os.environ.get("LISTEN_PORT")
    # 1241 is reserved by Windows on this machine; ignore stale shell settings.
    listen_port = int(configured_port) if configured_port and configured_port != "1241" else 18080
    uvicorn.run(
        "server.app:app",
        host=os.environ.get("LISTEN_HOST") or "127.0.0.1",
        port=listen_port,
        reload=True,
        reload_dirs=["server", "lib"],
    )
