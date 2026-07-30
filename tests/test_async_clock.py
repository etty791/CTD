import pytest

from observability.metrics import default_registry
from observability.metrics_config import DRAIN_LOOP_LAG_SECONDS
from server.async_clock import AsyncClock
from server.server_config import TICK_MS


def _lag_sample():
    return default_registry.histogram(DRAIN_LOOP_LAG_SECONDS).sample()


class TestRecordLag:
    """`_record_lag` is exercised directly rather than through a real
    `asyncio.sleep`-driven `every` loop, so this stays sleep-free like the
    rest of the suite.

    `server/async_clock.py` registers its `drain_loop_lag_seconds` histogram
    once at import time and holds onto that instrument object; asserting on
    *deltas* (rather than resetting the shared default_registry, which would
    hand back a fresh, disconnected instrument under the same name) keeps
    this test independent of whatever else in the suite has already
    observed into it.
    """

    def test_exact_tick_observes_zero_lag(self):
        before = _lag_sample()
        clock = AsyncClock(TICK_MS)
        clock._record_lag(TICK_MS)
        after = _lag_sample()
        assert after.counts[()] == before.counts.get((), 0) + 1
        assert after.sums[()] == pytest.approx(before.sums.get((), 0.0))

    def test_overshoot_observes_positive_lag_in_seconds(self):
        before = _lag_sample()
        clock = AsyncClock(TICK_MS)
        clock._record_lag(TICK_MS + 20)  # 20ms over
        after = _lag_sample()
        assert after.sums[()] == pytest.approx(before.sums.get((), 0.0) + 0.02)

    def test_multiple_ticks_accumulate(self):
        before = _lag_sample()
        clock = AsyncClock(TICK_MS)
        clock._record_lag(TICK_MS + 10)
        clock._record_lag(TICK_MS + 10)
        after = _lag_sample()
        assert after.counts[()] == before.counts.get((), 0) + 2
        assert after.sums[()] == pytest.approx(before.sums.get((), 0.0) + 0.02)


class TestNowMs:
    async def test_returns_an_int_ms_value(self):
        clock = AsyncClock(TICK_MS)
        now = clock.now_ms()
        assert isinstance(now, int)
        assert now >= 0
