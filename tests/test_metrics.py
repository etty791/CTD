import pytest

from observability.metrics import (
    CardinalityError,
    Counter,
    Histogram,
    MetricRedefinedError,
    MetricsRegistry,
    UnknownLabelError,
)


@pytest.fixture
def registry() -> MetricsRegistry:
    return MetricsRegistry()


class TestCounter:
    def test_inc_defaults_to_one(self, registry):
        c = registry.counter("requests_total")
        c.inc()
        c.inc()
        assert c.sample().values[()] == 2

    def test_inc_by_amount(self, registry):
        c = registry.counter("bytes_total")
        c.inc(10)
        c.inc(5)
        assert c.sample().values[()] == 15

    def test_labeled_counts_are_independent(self, registry):
        c = registry.counter("events_total", ("event",))
        c.inc(event="MoveStarted")
        c.inc(event="MoveStarted")
        c.inc(event="PieceCaptured")
        sample = c.sample()
        assert sample.values[("MoveStarted",)] == 2
        assert sample.values[("PieceCaptured",)] == 1

    def test_missing_label_raises(self, registry):
        c = registry.counter("events_total", ("event",))
        with pytest.raises(UnknownLabelError):
            c.inc()

    def test_unexpected_label_raises(self, registry):
        c = registry.counter("events_total", ("event",))
        with pytest.raises(UnknownLabelError):
            c.inc(event="X", extra="Y")


class TestHistogram:
    def test_observe_tracks_count_and_sum(self, registry):
        h = registry.histogram("frame_bytes")
        h.observe(100)
        h.observe(200)
        sample = h.sample()
        assert sample.counts[()] == 2
        assert sample.sums[()] == 300

    def test_labeled_observations_are_independent(self, registry):
        h = registry.histogram("frame_bytes", ("type",))
        h.observe(100, type="state")
        h.observe(50, type="event")
        sample = h.sample()
        assert sample.counts[("state",)] == 1
        assert sample.counts[("event",)] == 1


class TestCardinalityDiscipline:
    @pytest.mark.parametrize("forbidden", ["game_id", "user_id", "session_id"])
    def test_counter_rejects_forbidden_label(self, registry, forbidden):
        with pytest.raises(CardinalityError):
            registry.counter("some_metric", (forbidden,))

    @pytest.mark.parametrize("forbidden", ["game_id", "user_id", "session_id"])
    def test_histogram_rejects_forbidden_label(self, registry, forbidden):
        with pytest.raises(CardinalityError):
            registry.histogram("some_metric", (forbidden,))

    def test_bare_counter_construction_also_rejects(self):
        with pytest.raises(CardinalityError):
            Counter("some_metric", ("user_id",))

    def test_bare_histogram_construction_also_rejects(self):
        with pytest.raises(CardinalityError):
            Histogram("some_metric", ("game_id",))


class TestRegistration:
    def test_same_signature_returns_same_instrument(self, registry):
        a = registry.counter("requests_total", ("type",))
        b = registry.counter("requests_total", ("type",))
        assert a is b

    def test_conflicting_signature_raises(self, registry):
        registry.counter("requests_total", ("type",))
        with pytest.raises(MetricRedefinedError):
            registry.counter("requests_total", ("event",))

    def test_counter_vs_histogram_namespaces_are_independent(self, registry):
        registry.counter("thing_total")
        # A histogram with the same name is a different instrument kind and
        # tracked separately - no collision.
        h = registry.histogram("thing_total")
        assert h is not None


class TestSnapshot:
    def test_snapshot_includes_all_instruments(self, registry):
        c = registry.counter("a_total")
        c.inc()
        h = registry.histogram("b_seconds")
        h.observe(1.0)

        snapshot = registry.snapshot()
        assert len(snapshot.counters) == 1
        assert len(snapshot.histograms) == 1
        assert snapshot.counters[0].name == "a_total"
        assert snapshot.histograms[0].name == "b_seconds"

    def test_reset_clears_everything(self, registry):
        registry.counter("a_total").inc()
        registry.reset()
        assert registry.snapshot() == registry.snapshot()
        assert registry.snapshot().counters == ()
        assert registry.snapshot().histograms == ()
