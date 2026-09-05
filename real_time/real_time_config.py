from enum import Enum

DEFAULT_MOVE_DELAY_MS = 1000
LONG_REST_DURATION_MS = 2 * DEFAULT_MOVE_DELAY_MS
SHORT_REST_DURATION_MS = DEFAULT_MOVE_DELAY_MS


class SchedulerKind(str, Enum):
    """Which of RealTimeArbiter's two internal drains advance_time uses.
    TICK_SWEEP is the original every-call full resweep; EVENT_HEAP is the
    MIGRATION.md phase-2 discrete-event scheduler. Both are exercised by
    tests/test_scheduler_equivalence.py; TICK_SWEEP exists only until that
    harness has proven the heap equivalent, at which point it and this flag
    are deleted (see MIGRATION.md phase 2 status)."""
    TICK_SWEEP = "tick_sweep"
    EVENT_HEAP = "event_heap"


DEFAULT_SCHEDULER = SchedulerKind.EVENT_HEAP
