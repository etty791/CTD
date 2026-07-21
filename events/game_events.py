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
class PieceCaptured:
    piece_id: Any
    piece_type: PieceType
    color: Color
    position: Position
    capturing_move_id: int


@dataclass(frozen=True)
class ScoreChanged:
    color: Color
    score: int
