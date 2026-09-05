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
    """A move was accepted and is now in flight. `start_time_ms` and
    `arrival_time_ms` are the move's absolute clock bounds, carried here so
    consumers on the wire never have to re-derive travel timing (which is
    the arbiter's business, not theirs)."""
    move_id: int
    piece_id: Any
    src: Position
    dst: Position
    start_time_ms: int
    arrival_time_ms: int


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
    """A move ended somewhere other than the target it was ordered to.

    Two cases, told apart by `in_flight`:
    - True: shortened mid-flight by a same-color blocker. The piece is still
      travelling, but toward `target`, arriving at `arrival_time_ms`.
    - False: the move is over. The piece has already been placed on `target`
      (it had vacated its origin and retreated there) and is resting.
    """
    move_id: int
    piece_id: Any
    target: Position
    arrival_time_ms: int
    in_flight: bool


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
