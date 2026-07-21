import time
from dataclasses import dataclass
from typing import Any, List

from model.piece import Color, PieceType
from model.position import Position
from events.event_bus import EventBus
from events.game_events import MoveCompleted, PieceCaptured


@dataclass(frozen=True)
class MoveLogEntry:
    piece_id: Any
    piece_type: PieceType
    color: Color
    src: Position
    dst: Position
    was_capture: bool
    timestamp_ms: float


class MoveLog:
    """Records completed moves in order, correlating each with any capture
    it caused via the move's move_id - PieceCaptured always fires before
    the MoveCompleted of the move that caused it (both are published
    synchronously from the same arbiter call), so a capturing_move_id is
    always seen before its matching MoveCompleted arrives here."""

    def __init__(self, event_bus: EventBus):
        self._entries: List[MoveLogEntry] = []
        self._pending_captures: set = set()
        event_bus.subscribe(MoveCompleted, self._on_move_completed)
        event_bus.subscribe(PieceCaptured, self._on_piece_captured)

    def get_log(self) -> List[MoveLogEntry]:
        return list(self._entries)

    def _on_piece_captured(self, event: PieceCaptured) -> None:
        self._pending_captures.add(event.capturing_move_id)

    def _on_move_completed(self, event: MoveCompleted) -> None:
        was_capture = event.move_id in self._pending_captures
        self._pending_captures.discard(event.move_id)
        self._entries.append(MoveLogEntry(
            piece_id=event.piece_id,
            piece_type=event.piece_type,
            color=event.color,
            src=event.src,
            dst=event.dst,
            was_capture=was_capture,
            timestamp_ms=time.time() * 1000,
        ))
