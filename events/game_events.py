from dataclasses import dataclass
from typing import Any

from model.piece import Color, PieceType
from model.position import Position


@dataclass(frozen=True)
class GameStarted:
    pass


@dataclass(frozen=True)
class GameEnded:
    winner: Color


@dataclass(frozen=True)
class MoveStarted:
    move_id: int
    piece_id: Any
    src: Position
    dst: Position


@dataclass(frozen=True)
class MoveCompleted:
    move_id: int
    piece_id: Any
    piece_type: PieceType
    color: Color
    src: Position
    dst: Position


@dataclass(frozen=True)
class MoveTruncated:
    """A move was shortened mid-flight by a same-color blocker: its piece is
    still travelling, but toward `target`, arriving at `arrival_time_ms`."""
    move_id: int
    piece_id: Any
    target: Position
    arrival_time_ms: int


@dataclass(frozen=True)
class MoveAborted:
    """A move ended without its piece ever reaching a new cell - blocked
    before its first step, or invalidated by the time it arrived. The piece
    rests at `position`; no MoveCompleted follows."""
    move_id: int
    piece_id: Any
    position: Position


@dataclass(frozen=True)
class RestEnded:
    """A piece's cooldown elapsed: it is back in State.idle and commandable."""
    piece_id: Any
    position: Position


@dataclass(frozen=True)
class PieceCaptured:
    piece_id: Any
    piece_type: PieceType
    color: Color
    position: Position
    capturing_move_id: int
