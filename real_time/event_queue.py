"""A per-game discrete-event heap, ordered by `(time_ms, kind_priority,
monotonic_seq)` - spec MIGRATION.md phase 2's `(game_time, monotonic_seq)`
determinism rule, refined with one extra tier: `kind_priority` reproduces the
step order the legacy tick sweep used within one instant (collisions resolve,
then origins vacate, then arrivals apply, then rests release), so events that
land on the exact same millisecond are still handled in the order the rest of
the arbiter assumes. Both tiers are pure functions of already-deterministic
inputs - no wall-clock reads, no randomness.

Lazy invalidation: nothing is ever removed from the heap directly. Rescheduling
or cancelling an event for a given `(kind, key)` bumps that key's generation
counter; a popped entry whose stamped generation no longer matches the current
one for its key is silently discarded. This is what lets a move be truncated
(retargeting its MOVE_DONE event) or a piece be captured mid-rest (cancelling
its REST_END) without a heap-wide scan.
"""

import heapq
import itertools
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class EventKind(IntEnum):
    """Priority order within one millisecond, matching the legacy sweep's
    per-tick step order exactly: _resolve_path_collisions, then
    _vacate_departed_origins, then arrivals, then _release_expired_rests."""
    COLLISION = 0
    VACATE = 1
    MOVE_DONE = 2
    REST_END = 3


@dataclass(frozen=True)
class ScheduledEvent:
    time_ms: int
    kind: EventKind
    key: Any
    payload: Any = None


@dataclass(order=True)
class _HeapEntry:
    sort_key: tuple = field(compare=True)
    event: ScheduledEvent = field(compare=False)
    generation: int = field(compare=False)


class EventQueue:
    def __init__(self):
        self._heap: list[_HeapEntry] = []
        self._generations: dict[tuple, int] = {}
        self._seq = itertools.count()

    def _gen_key(self, kind: EventKind, key: Any) -> tuple:
        return (kind, key)

    def schedule(self, time_ms: int, kind: EventKind, key: Any, payload: Any = None) -> None:
        """(Re)schedule the event for `(kind, key)`, invalidating whatever
        was previously scheduled for it - a key has at most one live event
        per kind at a time."""
        gen_key = self._gen_key(kind, key)
        generation = self._generations.get(gen_key, 0) + 1
        self._generations[gen_key] = generation
        event = ScheduledEvent(time_ms, kind, key, payload)
        sort_key = (time_ms, kind, next(self._seq))
        heapq.heappush(self._heap, _HeapEntry(sort_key, event, generation))

    def cancel(self, kind: EventKind, key: Any) -> None:
        """Invalidate whatever is scheduled for `(kind, key)` without
        scheduling a replacement."""
        gen_key = self._gen_key(kind, key)
        self._generations[gen_key] = self._generations.get(gen_key, 0) + 1

    def _is_live(self, entry: _HeapEntry) -> bool:
        gen_key = self._gen_key(entry.event.kind, entry.event.key)
        return self._generations.get(gen_key, 0) == entry.generation

    def _drop_stale_top(self) -> None:
        while self._heap and not self._is_live(self._heap[0]):
            heapq.heappop(self._heap)

    def peek_time(self) -> Optional[int]:
        """The time of the earliest live event, or None if the queue is
        empty (every scheduled event has since been superseded or
        cancelled)."""
        self._drop_stale_top()
        return self._heap[0].event.time_ms if self._heap else None

    def pop_due_at(self, time_ms: int) -> list[ScheduledEvent]:
        """Pop every live event at exactly `time_ms`, in
        `(kind_priority, seq)` order. Caller is expected to have already
        confirmed `peek_time() == time_ms`."""
        due: list[ScheduledEvent] = []
        while self._heap:
            self._drop_stale_top()
            if not self._heap or self._heap[0].event.time_ms != time_ms:
                break
            due.append(heapq.heappop(self._heap).event)
        return due

    def is_empty(self) -> bool:
        return self.peek_time() is None
