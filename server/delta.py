"""DeltaBuilder: turns the engine's event stream into delta frames.

Deltas are built from events, never by diffing snapshots. That falls out of
the arbiter being the only publisher of state changes (so an event exists for
every change) and is why a mutation without an event is invisible to clients -
the same reason the old STATE broadcast was event-driven.

One event becomes one op (`server/encoding.py: op_from_event`); a whole pass of
the engine becomes one frame, however many events it published. Scores are the
one thing with no event of its own: ScoreTracker stays silent, so the builder
reads them on drain and emits an `sc` op only when they actually moved.
"""

from typing import Callable

from model.piece import Color
from observability.metrics import counter
from observability.metrics_config import GAME_STATE_EVENTS_TOTAL, LABEL_EVENT
from server.encoding import op_from_event, scores_op

ScoresReader = Callable[[], dict[Color, int]]

_game_state_events_total = counter(GAME_STATE_EVENTS_TOTAL, (LABEL_EVENT,))


class DeltaBuilder:
    def __init__(self, read_scores: ScoresReader):
        self._read_scores = read_scores
        self._ops: list[list] = []
        # Seeded from the opening scores, which the first keyframe already
        # carries - so the first delta doesn't restate them for nothing.
        self._last_scores = read_scores()

    def on_event(self, event) -> None:
        """SYNC bus handler, subscribed to every STATE_CHANGING_EVENT. An
        event with no op of its own (GameEnded, whose end-of-game GAME_OVER
        reports) is counted and dropped: it never arrives alone, since the
        capture that ended the game publishes an op in the same pass."""
        _game_state_events_total.inc(event=type(event).__name__)
        op = op_from_event(event)
        if op is not None:
            self._ops.append(op)

    def has_ops(self) -> bool:
        return bool(self._ops)

    def drain(self) -> list[list]:
        """Take every buffered op, appending an `sc` op if the scores changed
        since the last drain. Empties the buffer."""
        ops, self._ops = self._ops, []
        scores = self._read_scores()
        if scores != self._last_scores:
            self._last_scores = scores
            ops.append(scores_op(scores))
        return ops
