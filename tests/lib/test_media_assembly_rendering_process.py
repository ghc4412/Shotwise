from __future__ import annotations

import asyncio

import pytest

from lib.media_assembly import rendering

pytestmark = pytest.mark.unit


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr_chunks: list[tuple[float, bytes]] | None = None,
        delay: float = 0.0,
        returncode: int = 0,
    ) -> None:
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None
        self.killed = False
        self._stdout = stdout
        self._stderr_chunks = stderr_chunks or []
        self._delay = delay
        self._exit_code = returncode
        self._finished = asyncio.Event()
        self._settle_task = asyncio.create_task(self._settle())

    async def _settle(self) -> None:
        for delay, chunk in self._stderr_chunks:
            await asyncio.sleep(delay)
            self.stderr.feed_data(chunk)
        await asyncio.sleep(self._delay)
        if self._stdout:
            self.stdout.feed_data(self._stdout)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = self._exit_code
        self._finished.set()

    async def wait(self) -> int:
        await self._finished.wait()
        assert self.returncode is not None
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._settle_task.cancel()
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._finished.set()


def _install_process(monkeypatch: pytest.MonkeyPatch, process: _FakeProcess) -> list[list[str]]:
    calls: list[list[str]] = []

    async def fake_exec(*args: str, **_: object) -> _FakeProcess:
        calls.append(list(args))
        return process

    monkeypatch.setattr(rendering.asyncio, "create_subprocess_exec", fake_exec)
    return calls


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"", None),
        (b"time=00:01:02.50", 62.5),
        (b"time=00:00:01.00 frame=1 time=00:00:03.25 frame=2", 3.25),
    ],
)
def test_parse_ffmpeg_seconds_uses_the_latest_position(stderr: bytes, expected: float | None) -> None:
    assert rendering._parse_ffmpeg_seconds(stderr) == expected


async def test_progress_and_cancel_callbacks_support_sync_async_and_awaitables() -> None:
    loop = asyncio.get_running_loop()
    progress_sync: list[float] = []
    progress_async: list[float] = []
    progress_future: asyncio.Future[None] = loop.create_future()
    progress_future.set_result(None)
    cancel_future: asyncio.Future[bool] = loop.create_future()
    cancel_future.set_result(True)

    def on_progress_sync(value: float) -> None:
        progress_sync.append(value)

    async def on_progress_async(value: float) -> None:
        progress_async.append(value)

    await rendering._invoke_progress(None, 0.5)
    await rendering._invoke_progress(on_progress_sync, -1.0)
    await rendering._invoke_progress(on_progress_async, 2.0)
    await rendering._invoke_progress(lambda _value: progress_future, 0.25)

    assert progress_sync == [0.0]
    assert progress_async == [1.0]
    assert await rendering._invoke_cancel_check(None) is False
    assert await rendering._invoke_cancel_check(lambda: True) is True
    assert await rendering._invoke_cancel_check(lambda: cancel_future) is True


async def test_run_process_reports_final_progress_when_it_finishes_before_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = b"frame=1 time=00:00:04.20 speed=1x"
    process = _FakeProcess(stdout=b"stdout", stderr_chunks=[(0.0, stderr)])
    calls = _install_process(monkeypatch, process)
    updates: list[float] = []

    stdout, captured_stderr = await rendering._run_process(
        ["ffmpeg", "-i", "input.mp4"],
        timeout_seconds=1.0,
        on_progress=updates.append,
        total_duration_seconds=10.0,
        poll_interval_seconds=0.05,
    )

    assert calls == [["ffmpeg", "-i", "input.mp4"]]
    assert stdout == b"stdout"
    assert captured_stderr == stderr
    assert updates == [pytest.approx(0.42)]


async def test_run_process_reports_progress_between_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(
        stderr_chunks=[
            (0.0, b"time=00:00:02.00"),
            (0.04, b" time=00:00:04.00"),
        ],
        delay=0.08,
    )
    _install_process(monkeypatch, process)
    updates: list[float] = []

    await rendering._run_process(
        ["ffmpeg"],
        timeout_seconds=1.0,
        on_progress=updates.append,
        total_duration_seconds=10.0,
        poll_interval_seconds=0.01,
    )

    assert updates == [pytest.approx(0.2), pytest.approx(0.4)]


async def test_run_process_cancellation_kills_the_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(delay=10.0)
    _install_process(monkeypatch, process)

    async def cancel_check() -> bool:
        return True

    with pytest.raises(rendering.RenderCancelledError) as exc_info:
        await rendering._run_process(
            ["ffmpeg"],
            timeout_seconds=1.0,
            cancel_check=cancel_check,
            poll_interval_seconds=0.01,
        )

    assert exc_info.value.code == "media_process_cancelled"
    assert process.killed is True


async def test_run_process_timeout_kills_the_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(delay=10.0)
    _install_process(monkeypatch, process)

    with pytest.raises(rendering.RenderToolError) as exc_info:
        await rendering._run_process(
            ["ffmpeg"],
            timeout_seconds=0.03,
            poll_interval_seconds=0.01,
        )

    assert exc_info.value.code == "media_process_timeout"
    assert process.killed is True


async def test_run_process_surfaces_return_code_and_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(stderr_chunks=[(0.0, b"encoder failed")], returncode=2)
    _install_process(monkeypatch, process)

    with pytest.raises(rendering.RenderToolError) as exc_info:
        await rendering._run_process(["ffmpeg"], timeout_seconds=1.0, poll_interval_seconds=0.01)

    assert exc_info.value.code == "media_process_failed"
    assert "encoder failed" in exc_info.value.message
