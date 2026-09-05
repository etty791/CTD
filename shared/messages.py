"""Pydantic payload models for the WebSocket protocol.

Each `MessageType` that carries a structured payload gets a dedicated model
here so handlers validate `Envelope.payload`.

These models depend on `model/` only: encoding a server-side `GameSnapshot`
into a `KeyframePayload` lives in `server/encoding.py`, so the wire contract
stays free of `game_engine` knowledge the client has no use for.
"""
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from model.board import BOARD_SIZE
from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
from model.position import Position

# A piece that is not mid-move has made no progress through one.
IDLE_PROGRESS = 0.0
# Sentinel for a frame built before any real clock reading is known.
NO_SERVER_TIME_MS = 0


class PositionPayload(BaseModel):
    x: int = Field(ge=0, lt=BOARD_SIZE)
    y: int = Field(ge=0, lt=BOARD_SIZE)

    @classmethod
    def from_position(cls, position: Position) -> "PositionPayload":
        return cls(x=position.x, y=position.y)

    def to_position(self) -> Position:
        return Position(self.x, self.y)


class CredentialsPayload(BaseModel):
    username: str
    password: str


class AuthAckPayload(BaseModel):
    status: str
    player_id: str
    rating: int | None = None


class ErrorPayload(BaseModel):
    message: str


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
    """One piece as seen on the wire.

    A moving piece carries the absolute start/arrival times of its move
    rather than a sampled progress fraction: state frames are published on
    change, not on a timer, so the receiver interpolates the motion itself
    against the frame's server_time_ms. Both are None for a piece at rest,
    where origin == target == position.
    """

    id: int
    position: PositionPayload
    type: str
    color: str
    state: str
    origin: PositionPayload
    target: PositionPayload
    move_start_ms: int | None = None
    move_arrival_ms: int | None = None

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
            move_start_ms=piece.move_start_ms,
            move_arrival_ms=piece.move_arrival_ms,
        )

    def to_piece_dto(self, progress: float = IDLE_PROGRESS) -> PieceDTO:
        """`progress` is supplied by the caller, which alone knows how much
        time has passed since the frame was encoded."""
        return PieceDTO(
            id=self.id,
            position=self.position.to_position(),
            type=PieceType(self.type),
            color=Color(self.color),
            state=State(self.state),
            origin=self.origin.to_position(),
            target=self.target.to_position(),
            progress=progress,
            move_start_ms=self.move_start_ms,
            move_arrival_ms=self.move_arrival_ms,
        )


class KeyframePayload(BaseModel):
    """A whole game state. The universal recovery path: game start, observer
    join, and a client-detected sequence gap all resolve to one of these."""

    pieces: List[PiecePayload]
    scores: Dict[str, int]
    # The sender's game clock when this frame was encoded; the timebase every
    # piece's move_start_ms/move_arrival_ms is expressed in.
    server_time_ms: int = NO_SERVER_TIME_MS


class DeltaPayload(BaseModel):
    """The changes since the previous frame, as positional-array ops (see
    `shared/delta_ops.py` for their layout).

    `server_time_ms` is per frame rather than per op because it is what the
    receiver re-anchors its motion interpolation against: without a fresh
    reading every frame, a moving piece's progress would drift from the
    server's clock over the life of a game."""

    ops: List[List[Any]] = Field(default_factory=list)
    server_time_ms: int = NO_SERVER_TIME_MS
