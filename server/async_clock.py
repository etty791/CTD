import asyncio
from typing import Callable

from observability.metrics import histogram
from observability.metrics_config import DRAIN_LOOP_LAG_SECONDS
from shared.protocol_config import MS_PER_SECOND

_drain_loop_lag_seconds = histogram(DRAIN_LOOP_LAG_SECONDS)


class TimerHandle:
    """Cancellable handle to a scheduled callback."""

    def __init__(self, task: asyncio.Task):
        self._task = task

    def cancel(self) -> None:
        self._task.cancel()


class AsyncClock:
    """Asyncio-based timer source shared by every server-side timing need:
    driving a game's RealTimeArbiter, disconnect-grace countdowns, and
    matchmaking timeouts. Callers never touch asyncio directly, so the
    whole server's timing can be swapped out or faked in tests via this
    one class instead of three bespoke loops.
    """

    def __init__(self, tick_ms: int):
        self._tick_ms = tick_ms

    def _record_lag(self, elapsed_ms: int) -> None:
        """Spec §19's single most important internal metric: how far a
        tick's actual elapsed time overshot the requested tick_ms. Split
        out from `every` so it can be unit-tested directly without
        sleeping on a real event loop.
        """
        lag_seconds = (elapsed_ms - self._tick_ms) / MS_PER_SECOND
        _drain_loop_lag_seconds.observe(lag_seconds)

    def now_ms(self) -> int:
        """The clock's own notion of 'now', so callers needing a
        timestamp (e.g. matchmaking's widening band) never read real time
        directly and so this is the one place tests fake wholesale.
        """
        return int(asyncio.get_event_loop().time() * MS_PER_SECOND)

    def every(self, callback: Callable[[int], None]) -> TimerHandle:
        """Call `callback(elapsed_ms)` once per tick, forever, until the
        returned handle is cancelled. `elapsed_ms` is measured off the
        event loop's own clock rather than assumed to equal tick_ms, so a
        stalled loop iteration doesn't desync game time from real time.
        Intended use: `clock.every(lambda ms: game.wait(ms))` per active
        game.
        """
        async def _loop():
            loop = asyncio.get_event_loop()
            last = loop.time()
            while True:
                await asyncio.sleep(self._tick_ms / 1000)
                now = loop.time()
                elapsed_ms = int((now - last) * 1000)
                last = now
                self._record_lag(elapsed_ms)
                callback(elapsed_ms)
        return TimerHandle(asyncio.create_task(_loop()))

    def after(self, delay_ms: int, callback: Callable[[], None]) -> TimerHandle:
        """Call `callback()` once after delay_ms, unless the returned
        handle is cancelled first. Intended use: disconnect-grace
        countdowns (cancel on reconnect) and matchmaking timeouts (cancel
        once a match is found).
        """
        async def _wait():
            await asyncio.sleep(delay_ms / 1000)
            callback()
        return TimerHandle(asyncio.create_task(_wait()))
