"""Pydantic payload models for the WebSocket protocol.

Each `MessageType` that carries a structured payload gets a dedicated model
here so handlers validate `Envelope.payload`
"""
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field

from game_engine.payloads import GameStatePayload, PiecePayload as PieceDataclassPayload
from model.position import Position


class PositionPayload(BaseModel):
    x: int
    y: int

    @classmethod
    def from_position(cls, position: Position) -> "PositionPayload":
        return cls(x=position.x, y=position.y)

    def to_position(self) -> Position:
        return Position(self.x, self.y)


class AuthPayload(BaseModel):
    player_id: str


class AuthAckPayload(BaseModel):
    status: str
    player_id: str


class ErrorPayload(BaseModel):
    message: str


class ResignPayload(BaseModel):
    reason: str


class MovePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: PositionPayload = Field(alias="from")
    to: PositionPayload


class PiecePayload(BaseModel):
    id: int
    position: PositionPayload
    type: str
    color: str
    state: str
    origin: PositionPayload
    target: PositionPayload
    progress: float

    @classmethod
    def from_piece_payload(cls, piece: PieceDataclassPayload) -> "PiecePayload":
        return cls(
            id=piece.id,
            position=PositionPayload(x=piece.position.x, y=piece.position.y),
            type=piece.type,
            color=piece.color,
            state=piece.state,
            origin=PositionPayload(x=piece.origin.x, y=piece.origin.y),
            target=PositionPayload(x=piece.target.x, y=piece.target.y),
            progress=piece.progress,
        )


class StatePayload(BaseModel):
    pieces: List[PiecePayload]
    scores: Dict[str, int]

    @classmethod
    def from_game_state_payload(cls, state: GameStatePayload) -> "StatePayload":
        return cls(
            pieces=[PiecePayload.from_piece_payload(piece) for piece in state.pieces],
            scores=dict(state.scores),
        )
