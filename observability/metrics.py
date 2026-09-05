"""A minimal in-process counter/histogram registry.

No Prometheus dependency yet - `MetricsRegistry.snapshot()` gives the bench
harness and tests a frozen read of every instrument; a `/metrics` text
exposition endpoint is a thin addition on top of that when a later phase
needs one.

Cardinality discipline is enforced at registration time, not at call time:
a metric may never be labeled by `game_id`/`user_id`/`session_id`
(`observability.metrics_config.FORBIDDEN_LABELS`), because those grow
without bound and would eventually take monitoring down with the system it
is meant to observe.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple

from observability.metrics_config import DEFAULT_BUCKETS, FORBIDDEN_LABELS


class CardinalityError(Exception):
    """A metric was declared with a label name that grows without bound."""

    def __init__(self, name: str, label_name: str):
        super().__init__(
            f"metric {name!r} may not be labeled by {label_name!r} (unbounded cardinality)"
        )
        self.name = name
        self.label_name = label_name


class MetricRedefinedError(Exception):
    """A metric name was re-registered with a different signature."""

    def __init__(self, name: str):
        super().__init__(f"metric {name!r} already registered with a different signature")
        self.name = name


class UnknownLabelError(Exception):
    """A recording call's label keys didn't match the metric's declaration."""

    def __init__(self, name: str, expected: Tuple[str, ...], got: Tuple[str, ...]):
        super().__init__(
            f"metric {name!r} expects labels {expected!r}, got {got!r}"
        )
        self.name = name


def _validate_label_names(name: str, label_names: Tuple[str, ...]) -> None:
    for label_name in label_names:
        if label_name in FORBIDDEN_LABELS:
            raise CardinalityError(name, label_name)


def _label_key(name: str, label_names: Tuple[str, ...], labels: Dict[str, str]) -> Tuple[str, ...]:
    if frozenset(labels.keys()) != frozenset(label_names):
        raise UnknownLabelError(name, label_names, tuple(labels.keys()))
    return tuple(labels[label_name] for label_name in label_names)


@dataclass(frozen=True)
class CounterSample:
    name: str
    label_names: Tuple[str, ...]
    values: Dict[Tuple[str, ...], float]


@dataclass(frozen=True)
class HistogramSample:
    name: str
    label_names: Tuple[str, ...]
    counts: Dict[Tuple[str, ...], int]
    sums: Dict[Tuple[str, ...], float]


class Counter:
    def __init__(self, name: str, label_names: Tuple[str, ...] = ()):
        _validate_label_names(name, label_names)
        self.name = name
        self.label_names = label_names
        self._values: Dict[Tuple[str, ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _label_key(self.name, self.label_names, labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def sample(self) -> CounterSample:
        return CounterSample(self.name, self.label_names, dict(self._values))


class Histogram:
    def __init__(
        self,
        name: str,
        label_names: Tuple[str, ...] = (),
        buckets: Tuple[float, ...] = DEFAULT_BUCKETS,
    ):
        _validate_label_names(name, label_names)
        self.name = name
        self.label_names = label_names
        self.buckets = buckets
        self._counts: Dict[Tuple[str, ...], int] = {}
        self._sums: Dict[Tuple[str, ...], float] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = _label_key(self.name, self.label_names, labels)
        self._counts[key] = self._counts.get(key, 0) + 1
        self._sums[key] = self._sums.get(key, 0.0) + value

    def sample(self) -> HistogramSample:
        return HistogramSample(self.name, self.label_names, dict(self._counts), dict(self._sums))


@dataclass(frozen=True)
class MetricsSnapshot:
    counters: Tuple[CounterSample, ...] = field(default_factory=tuple)
    histograms: Tuple[HistogramSample, ...] = field(default_factory=tuple)


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: Dict[str, Counter] = {}
        self._histograms: Dict[str, Histogram] = {}

    def counter(self, name: str, label_names: Tuple[str, ...] = ()) -> Counter:
        existing = self._counters.get(name)
        if existing is not None:
            if existing.label_names != tuple(label_names):
                raise MetricRedefinedError(name)
            return existing
        instrument = Counter(name, tuple(label_names))
        self._counters[name] = instrument
        return instrument

    def histogram(
        self,
        name: str,
        label_names: Tuple[str, ...] = (),
        buckets: Tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        existing = self._histograms.get(name)
        if existing is not None:
            if existing.label_names != tuple(label_names) or existing.buckets != tuple(buckets):
                raise MetricRedefinedError(name)
            return existing
        instrument = Histogram(name, tuple(label_names), tuple(buckets))
        self._histograms[name] = instrument
        return instrument

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(
            counters=tuple(c.sample() for c in self._counters.values()),
            histograms=tuple(h.sample() for h in self._histograms.values()),
        )

    def reset(self) -> None:
        self._counters.clear()
        self._histograms.clear()


default_registry = MetricsRegistry()


def counter(name: str, label_names: Tuple[str, ...] = ()) -> Counter:
    return default_registry.counter(name, label_names)


def histogram(
    name: str,
    label_names: Tuple[str, ...] = (),
    buckets: Tuple[float, ...] = DEFAULT_BUCKETS,
) -> Histogram:
    return default_registry.histogram(name, label_names, buckets)


def reset_default_registry() -> None:
    default_registry.reset()
