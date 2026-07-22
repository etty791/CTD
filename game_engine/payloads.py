from dataclasses import dataclass
from typing import Dict, List

from model.position import Position
from model.game_snapshot import PieceDTO
from rules.rules_engine import MoveValidation


@dataclass(frozen=True)
class PositionPayload:
    x: int
    y: int

    @classmethod
    def from_position(cls, position: Position) -> "PositionPayload":
        return cls(x=position.x, y=position.y)


@dataclass(frozen=True)
class PiecePayload:
    id: int
    position: PositionPayload
    type: str
    color: str
    state: str
    origin: PositionPayload
    target: PositionPayload
    progress: float

    @classmethod
    def from_piece_dto(cls, piece: PieceDTO) -> "PiecePayload":
        return cls(
            id=piece.id,
            position=PositionPayload.from_position(piece.position),
            type=piece.type.value,
            color=piece.color.value,
            state=piece.state.value,
            origin=PositionPayload.from_position(piece.origin),
            target=PositionPayload.from_position(piece.target),
            progress=piece.progress,
        )


@dataclass(frozen=True)
class MoveValidationPayload:
    is_valid: bool
    reason: str

    @classmethod
    def from_move_validation(cls, validation: MoveValidation) -> "MoveValidationPayload":
        return cls(is_valid=validation.is_valid, reason=validation.reason)


@dataclass(frozen=True)
class GameStatePayload:
    pieces: List[PiecePayload]
    scores: Dict[str, int]
