"""RemoteGame: adapts a networked game session to the exact surface view/ and
input/ expect from a local KungFuChessGame, so the OpenCV GUI and Controller
run completely unchanged over the network -- for both players and observers.

Three surfaces are involved, and only two objects implement them:

- `RemoteGameState` is one decoded server frame. It doubles as the
  `GameSnapshot` the renderer consumes (`get_all_pieces` / `get_scores`) and
  as the piece index the board view queries, so a STATE payload is decoded
  once when it arrives on the network thread rather than once per rendered
  frame. Only the animation progress of in-flight pieces is recomputed per
  frame -- frames arrive on change, not on a timer, so the client is what
  turns a move's start/arrival times into smooth motion.
- `RemoteBoardView` is the read-only slice of `Board` that `Controller` needs
  (`is_within_boundaries` / `is_cell_empty` / `get_piece_at`). It holds no
  state of its own -- it reads whichever `RemoteGameState` is current.

Pieces are plain `PieceDTO`s throughout: the controller only ever reads
`.color` off them, so there is no need for a client-side piece type.
"""

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from events.event_bus import EventBus
from events.game_events import (
    GameEnded,
    GameStarted,
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)
from model.board import EMPTY_CELL
from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType
from model.position import Position
from shared.messages import (
    NO_SERVER_TIME_MS,
    EventPayload,
    GameOverPayload,
    JumpPayload,
    MovePayload,
    PositionPayload,
    StatePayload,
)
from shared.protocol import Envelope, MessageType
from view.view_config import DEFAULT_BOARD_SIZE, MS_PER_SECOND

OBSERVER_CANNOT_MOVE_REASON = "observer_cannot_move"
MOVE_OK_REASON = "ok"
NO_SCORE = 0
MOVE_NOT_STARTED = 0.0
MOVE_FINISHED = 1.0
# No frame has ever been received yet -- there is no "ago" to measure.
NO_FRAME_RECEIVED_S = 0.0


@dataclass(frozen=True)
class RemoteMoveResult:
    """Client-side stand-in for rules.rules_engine.MoveValidation: same
    (is_valid, reason) shape, defined locally so the client never imports
    the rules/ layer - the server is the sole validator of moves."""

    is_valid: bool
    reason: str


@dataclass(frozen=True)
class RemoteGameState:
    """One decoded STATE frame. Immutable, so the network thread can swap a
    fresh one in wholesale while the render thread reads the previous one.

    The server publishes frames on change rather than on a timer, so a frame
    describes a moving piece by the absolute clock times its move spans, not
    by a progress fraction that would freeze between frames. `get_all_pieces`
    resolves those times against how long ago the frame landed, which is why
    it renders smoothly at frame rate off a state that may be a full second
    old. Latency shifts every piece by the same constant, so it needs no
    clock synchronisation with the server."""

    pieces: tuple[PieceDTO, ...] = ()
    scores: dict[Color, int] = field(
        default_factory=lambda: {Color.WHITE: NO_SCORE, Color.BLACK: NO_SCORE}
    )
    by_position: dict[Position, PieceDTO] = field(default_factory=dict)
    server_time_ms: int = NO_SERVER_TIME_MS
    received_at_s: float = NO_FRAME_RECEIVED_S

    @classmethod
    def from_payload(cls, payload: StatePayload, received_at_s: float | None = None) -> "RemoteGameState":
        pieces = tuple(piece.to_piece_dto() for piece in payload.pieces)
        return cls(
            pieces=pieces,
            scores={Color(color): score for color, score in payload.scores.items()},
            by_position={piece.position: piece for piece in pieces},
            server_time_ms=payload.server_time_ms,
            received_at_s=time.monotonic() if received_at_s is None else received_at_s,
        )

    # --- the GameSnapshot surface view/ renders from ---
    def get_all_pieces(self, now_s: float | None = None) -> list[PieceDTO]:
        now = time.monotonic() if now_s is None else now_s
        return [replace(piece, progress=self._progress_of(piece, now)) for piece in self.pieces]

    def get_scores(self) -> dict[Color, int]:
        return dict(self.scores)

    def _progress_of(self, piece: PieceDTO, now_s: float) -> float:
        """How far `piece` is through its move as of `now_s`, clamped: a
        piece whose arrival frame is still in flight parks on its target
        square rather than sliding past it."""
        if piece.move_start_ms is None or piece.move_arrival_ms is None:
            return MOVE_NOT_STARTED
        duration_ms = piece.move_arrival_ms - piece.move_start_ms
        if duration_ms <= 0:
            return MOVE_FINISHED
        elapsed_ms = (now_s - self.received_at_s) * MS_PER_SECOND
        travelled_ms = self.server_time_ms + elapsed_ms - piece.move_start_ms
        return min(MOVE_FINISHED, max(MOVE_NOT_STARTED, travelled_ms / duration_ms))


def _decode_move_started(data: dict) -> MoveStarted:
    return MoveStarted(
        move_id=data["move_id"],
        piece_id=data["piece_id"],
        src=PositionPayload.model_validate(data["src"]).to_position(),
        dst=PositionPayload.model_validate(data["dst"]).to_position(),
    )


def _decode_move_completed(data: dict) -> MoveCompleted:
    return MoveCompleted(
        move_id=data["move_id"],
        piece_id=data["piece_id"],
        piece_type=PieceType(data["piece_type"]),
        color=Color(data["color"]),
        src=PositionPayload.model_validate(data["src"]).to_position(),
        dst=PositionPayload.model_validate(data["dst"]).to_position(),
    )


def _decode_move_truncated(data: dict) -> MoveTruncated:
    return MoveTruncated(
        move_id=data["move_id"],
        piece_id=data["piece_id"],
        target=PositionPayload.model_validate(data["target"]).to_position(),
        arrival_time_ms=data["arrival_time_ms"],
    )


def _decode_move_aborted(data: dict) -> MoveAborted:
    return MoveAborted(
        move_id=data["move_id"],
        piece_id=data["piece_id"],
        position=PositionPayload.model_validate(data["position"]).to_position(),
    )


def _decode_piece_captured(data: dict) -> PieceCaptured:
    return PieceCaptured(
        piece_id=data["piece_id"],
        piece_type=PieceType(data["piece_type"]),
        color=Color(data["color"]),
        position=PositionPayload.model_validate(data["position"]).to_position(),
        capturing_move_id=data["capturing_move_id"],
    )


def _decode_rest_ended(data: dict) -> RestEnded:
    return RestEnded(
        piece_id=data["piece_id"],
        position=PositionPayload.model_validate(data["position"]).to_position(),
    )


# Keyed off each dataclass's own name -- symmetric with server/encoding.py's
# _EVENT_ENCODERS, and immune to rename-drift since it's not a hand-typed
# string literal.
_EVENT_DECODERS: dict[str, Callable[[dict], object]] = {
    MoveStarted.__name__: _decode_move_started,
    MoveCompleted.__name__: _decode_move_completed,
    MoveTruncated.__name__: _decode_move_truncated,
    MoveAborted.__name__: _decode_move_aborted,
    PieceCaptured.__name__: _decode_piece_captured,
    RestEnded.__name__: _decode_rest_ended,
}


class RemoteBoardView:
    """The read-only slice of Board's API that Controller uses, backed by
    whichever game state is current."""

    def __init__(self, current_state: Callable[[], RemoteGameState]):
        self._current_state = current_state

    def is_within_boundaries(self, pos: Position) -> bool:
        return 0 <= pos.x < DEFAULT_BOARD_SIZE and 0 <= pos.y < DEFAULT_BOARD_SIZE

    def is_cell_empty(self, pos: Position) -> bool:
        return pos not in self._current_state().by_position

    def get_piece_at(self, pos: Position) -> PieceDTO | str:
        return self._current_state().by_position.get(pos, EMPTY_CELL)


class RemoteGame:
    def __init__(self, connection, is_observer: bool):
        self.events = EventBus()
        self.game_active = True
        self.game_over_payload: GameOverPayload | None = None
        self.board = RemoteBoardView(self.get_snapshot)
        self._connection = connection
        self._is_observer = is_observer
        self._state = RemoteGameState()
        self._started = False
        self._lock = threading.Lock()

    def move_request(self, origin: Position, target: Position) -> RemoteMoveResult:
        if self._is_observer:
            return RemoteMoveResult(False, OBSERVER_CANNOT_MOVE_REASON)
        self._connection.send(
            Envelope(
                type=MessageType.MOVE,
                payload=MovePayload(
                    from_=PositionPayload.from_position(origin),
                    to=PositionPayload.from_position(target),
                ).model_dump(by_alias=True),
            )
        )
        return RemoteMoveResult(True, MOVE_OK_REASON)

    def resign(self) -> None:
        if self._is_observer:
            return
        self._connection.send(Envelope(type=MessageType.RESIGN, payload={}))

    def jump_request(self, pos: Position) -> RemoteMoveResult:
        if self._is_observer:
            return RemoteMoveResult(False, OBSERVER_CANNOT_MOVE_REASON)
        self._connection.send(
            Envelope(
                type=MessageType.JUMP,
                payload=JumpPayload(pos=PositionPayload.from_position(pos)).model_dump(),
            )
        )
        return RemoteMoveResult(True, MOVE_OK_REASON)

    def wait(self, ms: int) -> None:
        if not self._started:
            self._started = True
            self.events.publish(GameStarted())
        # otherwise no-op: the server drives real time via ticking

    def get_snapshot(self) -> RemoteGameState:
        with self._lock:
            return self._state

    # --- called from the NETWORK thread ---
    def apply_state(self, state_payload: StatePayload) -> None:
        state = RemoteGameState.from_payload(state_payload)
        with self._lock:
            self._state = state

    def end_game(self, payload: GameOverPayload) -> None:
        self.game_active = False
        self.game_over_payload = payload
        self.events.publish(GameEnded(Color(payload.winner)))

    def apply_event(self, payload: EventPayload) -> None:
        decoder = _EVENT_DECODERS.get(payload.event_type)
        if decoder is None:
            return  # unknown/future event type -- ignore rather than crash the GUI
        self.events.publish(decoder(payload.data))
