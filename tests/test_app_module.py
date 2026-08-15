import asyncio
import sys
from types import SimpleNamespace

import pytest

import lib.db
import server.app as app_module
from server.routers import assistant as assistant_router

pytestmark = pytest.mark.unit


async def _noop_async(*args, **kwargs):
    """No-op coroutine for mocking async functions in tests."""


class _FakeWorker:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def request_cancel(self, _task_id: str) -> bool:
        return False


class TestAppModule:
    def test_create_generation_worker(self, monkeypatch):
        worker = _FakeWorker()
        monkeypatch.setattr(app_module, "GenerationWorker", lambda: worker)
        created = app_module.create_generation_worker()
        assert created is worker

    @pytest.mark.asyncio
    async def test_lifespan_starts_and_stops_worker(self, monkeypatch):
        worker = _FakeWorker()
        monkeypatch.setattr(app_module, "create_generation_worker", lambda: worker)
        monkeypatch.setattr(app_module, "ensure_auth_password", lambda: "test")
        monkeypatch.setattr(app_module, "init_db", _noop_async)
        monkeypatch.setattr(lib.db, "init_db", _noop_async)
        monkeypatch.setattr(assistant_router.assistant_service, "startup", _noop_async)
        monkeypatch.setattr(assistant_router.assistant_service, "shutdown", _noop_async)

        app = app_module.app
        app.state = SimpleNamespace()

        async with app_module.lifespan(app):
            assert worker.started
            assert hasattr(app.state, "generation_worker")

        assert worker.stopped

    @pytest.mark.asyncio
    async def test_lifespan_clears_callback_after_worker_stop(self, monkeypatch):
        """fix #647 #7：lifespan 应先 worker.stop()（drain inflight + callback 仍可用），
        再清掉 set_worker_cancel_callback(None)。
        """
        from lib.generation_queue import get_generation_queue

        # 用一个会在 stop() 时记录 callback 状态的 fake worker
        callback_during_stop: list[bool] = []
        queue = get_generation_queue()

        class _OrderCheckingWorker:
            def __init__(self):
                self.started = False
                self.stopped = False

            async def start(self):
                self.started = True

            async def stop(self):
                # 检查 stop() 调用期间 callback 还在
                callback_during_stop.append(queue._worker_cancel_callback is not None)
                self.stopped = True

            def request_cancel(self, _task_id: str) -> bool:
                return False

        worker = _OrderCheckingWorker()
        monkeypatch.setattr(app_module, "create_generation_worker", lambda: worker)
        monkeypatch.setattr(app_module, "ensure_auth_password", lambda: "test")
        monkeypatch.setattr(app_module, "init_db", _noop_async)
        monkeypatch.setattr(lib.db, "init_db", _noop_async)
        monkeypatch.setattr(assistant_router.assistant_service, "startup", _noop_async)
        monkeypatch.setattr(assistant_router.assistant_service, "shutdown", _noop_async)

        app = app_module.app
        app.state = SimpleNamespace()

        async with app_module.lifespan(app):
            # lifespan 启动后 callback 应已 set
            assert queue._worker_cancel_callback is not None

        # 关键断言：worker.stop() 调用期间 callback 仍然存在
        assert callback_during_stop == [True], f"stop() 时 callback 应仍可用，实际 {callback_during_stop}"
        # 退出后 callback 已清
        assert queue._worker_cancel_callback is None
        assert worker.stopped


class TestWindowsUvicornEventLoopPatch:
    """server/app.py 模块级的 Windows loop patch：uvicorn --reload 在 Windows 上
    会把事件循环退化为 SelectorEventLoop（Python 3.14 起不支持子进程），导致
    Claude Agent SDK 启动 claude.exe 时 NotImplementedError。patch 必须保证
    reload 模式也返回 ProactorEventLoop。

    有效性依赖本文件顶部 ``import server.app`` 触发模块级 patch；若 CI 无
    Windows job，这两个用例会被 skipif 跳过（Linux 下 patch 本就不生效）。
    """

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only fix")
    def test_reload_loop_factory_returns_proactor(self):
        from uvicorn.loops import asyncio as uvicorn_asyncio_loops

        # use_subprocess=True 对应 --reload / --workers>1 的 uvicorn 选择路径
        factory = uvicorn_asyncio_loops.asyncio_loop_factory(use_subprocess=True)
        loop = factory()
        try:
            assert isinstance(loop, asyncio.ProactorEventLoop)
        finally:
            loop.close()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only fix")
    def test_auto_loop_factory_respects_patch(self):
        from uvicorn.loops import auto as uvicorn_auto_loops

        factory = uvicorn_auto_loops.auto_loop_factory(use_subprocess=True)
        loop = factory()
        try:
            assert isinstance(loop, asyncio.ProactorEventLoop)
        finally:
            loop.close()
