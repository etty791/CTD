"""Pydantic payload models for the WebSocket protocol.

Each `MessageType` that carries a structured payload gets a dedicated model
here so handlers validate `Envelope.payload`.

These models depend on `model/` only: encoding a server-side `GameSnapshot`
into a `StatePayload` lives in `server/encoding.py`, so the wire contract
stays free of `game_engine` knowledge the client has no use for.
"""
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field

from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
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


class CredentialsPayload(BaseModel):
    username: str
    password: str


class AuthAckPayload(BaseModel):
    status: str
    player_id: str
    rating: int | None = None


class ErrorPayload(BaseModel):
    message: str


class ResignPayload(BaseModel):
    reason: str


class JoinRoomPayload(BaseModel):
    room_id: str


class RoomWaitingPayload(BaseModel):
    room_id: str
    status: str


class MovePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: PositionPayload = Field(alias="from")
    to: PositionPayload


class JumpPayload(BaseModel):
    pos: PositionPayload


class GameStartPayload(BaseModel):
    game_id: str
    role: str
    color: str | None
    white_username: str
    black_username: str


class RatingChangePayload(BaseModel):
    username: str
    old_rating: int
    new_rating: int


class GameOverPayload(BaseModel):
    winner: str
    reason: str
    rating_changes: List[RatingChangePayload] = Field(default_factory=list)


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

    def to_piece_dto(self) -> PieceDTO:
        return PieceDTO(
            id=self.id,
            position=self.position.to_position(),
            type=PieceType(self.type),
            color=Color(self.color),
            state=State(self.state),
            origin=self.origin.to_position(),
            target=self.target.to_position(),
            progress=self.progress,
        )


class StatePayload(BaseModel):
    pieces: List[PiecePayload]
    scores: Dict[str, int]
