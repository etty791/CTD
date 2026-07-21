from model.piece import Color
from events.event_bus import EventBus
from events.game_events import PieceCaptured, ScoreChanged
from game_engine.score_config import PIECE_VALUES


class ScoreTracker:
    """Authoritative running score per color, kept in sync purely by
    reacting to PieceCaptured events - the arbiter drives captures, this
    just tallies them."""

    def __init__(self, event_bus: EventBus):
        self._scores: dict[Color, int] = {Color.WHITE: 0, Color.BLACK: 0}
        event_bus.subscribe(PieceCaptured, self._on_piece_captured)
        self._event_bus = event_bus

    def get_score(self, color: Color) -> int:
        return self._scores[color]

    def _on_piece_captured(self, event: PieceCaptured) -> None:
        value = PIECE_VALUES.get(event.piece_type)
        if value is None:
            return
        capturing_color = Color.BLACK if event.color == Color.WHITE else Color.WHITE
        self._scores[capturing_color] += value
        self._event_bus.publish(ScoreChanged(capturing_color, self._scores[capturing_color]))
