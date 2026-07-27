"""RemoteGame: adapts a networked game session to the exact surface view/ and
input/ expect from a local KungFuChessGame, so the OpenCV GUI and Controller
run completely unchanged over the network -- for both players and observers.

Three surfaces are involved, and only two objects implement them:

- `RemoteGameState` is one decoded server frame. It doubles as the
  `GameSnapshot` the renderer consumes (`get_all_pieces` / `get_scores`) and
  as the piece index the board view queries, so a STATE payload is decoded
  once when it arrives on the network thread rather than once per rendered
  frame.
- `RemoteBoardView` is the read-only slice of `Board` that `Controller` needs
  (`is_within_boundaries` / `is_cell_empty` / `get_piece_at`). It holds no
  state of its own -- it reads whichever `RemoteGameState` is current.

Pieces are plain `PieceDTO`s throughout: the controller only ever reads
`.color` off them, so there is no need for a client-side piece type.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable

from events.event_bus import EventBus
from events.game_events import GameEnded, GameStarted
from model.board import EMPTY_CELL
from model.game_snapshot import PieceDTO
from model.piece import Color
from model.position import Position
from shared.messages import (
    GameOverPayload,
    JumpPayload,
    MovePayload,
    PositionPayload,
    StatePayload,
)
from shared.protocol import Envelope, MessageType
from view.view_config import DEFAULT_BOARD_SIZE

OBSERVER_CANNOT_MOVE_REASON = "observer_cannot_move"
MOVE_OK_REASON = "ok"
NO_SCORE = 0


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
    fresh one in wholesale while the render thread reads the previous one."""

    pieces: tuple[PieceDTO, ...] = ()
    scores: dict[Color, int] = field(
        default_factory=lambda: {Color.WHITE: NO_SCORE, Color.BLACK: NO_SCORE}
    )
    by_position: dict[Position, PieceDTO] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: StatePayload) -> "RemoteGameState":
        pieces = tuple(piece.to_piece_dto() for piece in payload.pieces)
        return cls(
            pieces=pieces,
            scores={Color(color): score for color, score in payload.scores.items()},
            by_position={piece.position: piece for piece in pieces},
        )

    # --- the GameSnapshot surface view/ renders from ---
    def get_all_pieces(self) -> list[PieceDTO]:
        return list(self.pieces)

    def get_scores(self) -> dict[Color, int]:
        return dict(self.scores)


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
