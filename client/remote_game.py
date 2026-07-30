"""RemoteGame: adapts a networked game session to the exact surface view/ and
input/ expect from a local KungFuChessGame, so the OpenCV GUI and Controller
run completely unchanged over the network -- for both players and observers.

Three surfaces are involved, and only two objects implement them:

- `RemoteGameState` is the client's copy of the game. It doubles as the
  `GameSnapshot` the renderer consumes (`get_all_pieces` / `get_scores`) and
  as the piece index the board view queries, so a frame is decoded once when
  it arrives on the network thread rather than once per rendered frame. Only
  the animation progress of in-flight pieces is recomputed per frame --
  frames arrive on change, not on a timer, so the client is what turns a
  move's start/arrival times into smooth motion.
- `RemoteBoardView` is the read-only slice of `Board` that `Controller` needs
  (`is_within_boundaries` / `is_cell_empty` / `get_piece_at`). It holds no
  state of its own -- it reads whichever `RemoteGameState` is current.

A KEYFRAME replaces the state wholesale; a DELTA applies its ops on top of it.
Applying ops produces a *new* frozen state rather than mutating the current
one, which is what lets the network thread swap it in under the render
thread's feet without either taking a lock across a whole rendered frame.

Every op also decodes back into the `events/` dataclass it was built from and
is republished on the local bus, which is what keeps the GUI's SoundPlayer
firing: a delta op is the per-event cue, not just a state diff.

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
from model.game_snapshot import PieceDTO
from model.piece import Color, PieceType, State
from model.position import Position
from shared import delta_ops
from shared.delta_ops import OpCode
from shared.messages import (
    NO_SERVER_TIME_MS,
    DeltaPayload,
    GameOverPayload,
    JumpPayload,
    KeyframePayload,
    MovePayload,
    PositionPayload,
)
from shared.protocol import Envelope, MessageType
from shared.protocol_config import DEFAULT_BOARD_SIZE, MS_PER_SECOND

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
    """The client's copy of the game, as of the last frame applied. Immutable,
    so the network thread can swap a fresh one in wholesale while the render
    thread reads the previous one.

    The server publishes frames on change rather than on a timer, so a frame
    describes a moving piece by the absolute clock times its move spans, not
    by a progress fraction that would freeze between frames. `get_all_pieces`
    resolves those times against how long ago the frame landed, which is why
    it renders smoothly at frame rate off a state that may be seconds old.
    Latency shifts every piece by the same constant, so it needs no clock
    synchronisation with the server.

    Pieces are keyed by id because that is how deltas address them; the
    by-position index the board view queries is derived alongside."""

    pieces: dict[int, PieceDTO] = field(default_factory=dict)
    scores: dict[Color, int] = field(
        default_factory=lambda: {Color.WHITE: NO_SCORE, Color.BLACK: NO_SCORE}
    )
    by_position: dict[Position, PieceDTO] = field(default_factory=dict)
    server_time_ms: int = NO_SERVER_TIME_MS
    received_at_s: float = NO_FRAME_RECEIVED_S

    @classmethod
    def _build(
        cls,
        pieces: dict[int, PieceDTO],
        scores: dict[Color, int],
        server_time_ms: int,
        received_at_s: float | None,
    ) -> "RemoteGameState":
        return cls(
            pieces=pieces,
            scores=scores,
            by_position={piece.position: piece for piece in pieces.values()},
            server_time_ms=server_time_ms,
            received_at_s=time.monotonic() if received_at_s is None else received_at_s,
        )

    @classmethod
    def from_keyframe(
        cls, payload: KeyframePayload, received_at_s: float | None = None
    ) -> "RemoteGameState":
        pieces = [piece.to_piece_dto() for piece in payload.pieces]
        return cls._build(
            pieces={piece.id: piece for piece in pieces},
            scores={Color(color): score for color, score in payload.scores.items()},
            server_time_ms=payload.server_time_ms,
            received_at_s=received_at_s,
        )

    def apply_delta(
        self, payload: DeltaPayload, received_at_s: float | None = None
    ) -> "RemoteGameState":
        """This state plus `payload`'s ops, as a new state. An op naming a
        piece this client has never heard of is skipped rather than raising -
        the same tolerance the old EVENT channel had for unknown events, and
        the seq check in client/network.py is what actually guarantees no op
        is ever missed."""
        pieces = dict(self.pieces)
        scores = dict(self.scores)
        for op in payload.ops:
            applier = _OP_APPLIERS.get(op[delta_ops.OP_CODE_INDEX])
            if applier is not None:
                applier(pieces, scores, op)
        return self._build(pieces, scores, payload.server_time_ms, received_at_s)

    # --- the GameSnapshot surface view/ renders from ---
    def get_all_pieces(self, now_s: float | None = None) -> list[PieceDTO]:
        now = time.monotonic() if now_s is None else now_s
        return [
            replace(piece, progress=self._progress_of(piece, now))
            for piece in self.pieces.values()
        ]

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


# --- delta ops: how each one changes the board ---------------------------
#
# Symmetric with server/encoding.py's _OP_ENCODERS. Field offsets come from
# shared/delta_ops.py so neither side indexes an op with a bare integer.
#
# Move ids are the server's business: the board only needs to know where each
# piece is and what it is doing, so the appliers ignore them. They matter to
# the decoded events further down, which correlate a capture with its move.

# Ops that end a move name the cell the piece came to rest on. There is no
# move left to interpolate, so origin and target collapse onto it.
def _settle(pieces: dict[int, PieceDTO], piece_id: int, cell: Position, state: State) -> None:
    piece = pieces.get(piece_id)
    if piece is None:
        return
    pieces[piece_id] = replace(
        piece,
        position=cell,
        origin=cell,
        target=cell,
        state=state,
        progress=MOVE_NOT_STARTED,
        move_start_ms=None,
        move_arrival_ms=None,
    )


def _apply_move_started(pieces, scores, op) -> None:
    piece = pieces.get(op[delta_ops.OP_PIECE_ID])
    if piece is None:
        return
    origin = Position(op[delta_ops.MOVE_STARTED_ORIGIN_X], op[delta_ops.MOVE_STARTED_ORIGIN_Y])
    target = Position(op[delta_ops.MOVE_STARTED_TARGET_X], op[delta_ops.MOVE_STARTED_TARGET_Y])
    # A jump goes nowhere: the piece stays on its square, airborne, for the
    # whole window. Anything else is a slide.
    state = State.airborne if origin == target else State.moving
    pieces[piece.id] = replace(
        piece,
        position=origin,
        origin=origin,
        target=target,
        state=state,
        move_start_ms=op[delta_ops.MOVE_STARTED_START_MS],
        move_arrival_ms=op[delta_ops.MOVE_STARTED_ARRIVAL_MS],
    )


def _apply_move_truncated(pieces, scores, op) -> None:
    piece_id = op[delta_ops.OP_PIECE_ID]
    target = Position(op[delta_ops.MOVE_TRUNCATED_TARGET_X], op[delta_ops.MOVE_TRUNCATED_TARGET_Y])
    if not op[delta_ops.MOVE_TRUNCATED_IN_FLIGHT]:
        # The move is over: the piece already retreated onto `target`.
        _settle(pieces, piece_id, target, State.long_rest)
        return
    piece = pieces.get(piece_id)
    if piece is None:
        return
    pieces[piece_id] = replace(
        piece,
        target=target,
        move_arrival_ms=op[delta_ops.MOVE_TRUNCATED_ARRIVAL_MS],
    )


def _apply_move_completed(pieces, scores, op) -> None:
    piece_id = op[delta_ops.OP_PIECE_ID]
    src = Position(op[delta_ops.MOVE_COMPLETED_SRC_X], op[delta_ops.MOVE_COMPLETED_SRC_Y])
    dst = Position(op[delta_ops.MOVE_COMPLETED_DST_X], op[delta_ops.MOVE_COMPLETED_DST_Y])
    # src == dst is a landed jump, which costs the shorter cooldown.
    _settle(pieces, piece_id, dst, State.short_rest if src == dst else State.long_rest)
    piece = pieces.get(piece_id)
    if piece is not None:
        # The one moment a piece's type can change: promotion, already
        # applied server-side before this op was encoded.
        pieces[piece_id] = replace(piece, type=PieceType(op[delta_ops.MOVE_COMPLETED_TYPE]))


def _apply_move_aborted(pieces, scores, op) -> None:
    cell = Position(op[delta_ops.MOVE_ABORTED_X], op[delta_ops.MOVE_ABORTED_Y])
    _settle(pieces, op[delta_ops.OP_PIECE_ID], cell, State.long_rest)


def _apply_piece_captured(pieces, scores, op) -> None:
    pieces.pop(op[delta_ops.OP_PIECE_ID], None)


def _apply_rest_ended(pieces, scores, op) -> None:
    cell = Position(op[delta_ops.REST_ENDED_X], op[delta_ops.REST_ENDED_Y])
    _settle(pieces, op[delta_ops.OP_PIECE_ID], cell, State.idle)


def _apply_scores(pieces, scores, op) -> None:
    scores[Color.WHITE] = op[delta_ops.SCORES_WHITE]
    scores[Color.BLACK] = op[delta_ops.SCORES_BLACK]


_OP_APPLIERS: dict[str, Callable[[dict, dict, list], None]] = {
    OpCode.MOVE_STARTED.value: _apply_move_started,
    OpCode.MOVE_TRUNCATED.value: _apply_move_truncated,
    OpCode.MOVE_COMPLETED.value: _apply_move_completed,
    OpCode.MOVE_ABORTED.value: _apply_move_aborted,
    OpCode.PIECE_CAPTURED.value: _apply_piece_captured,
    OpCode.REST_ENDED.value: _apply_rest_ended,
    OpCode.SCORES.value: _apply_scores,
}


# --- delta ops: the engine event each one came from ----------------------
#
# Republished on the local bus so client-side consumers of engine events
# (SoundPlayer, above all) work exactly as they do in a local game. `sc` has
# no event behind it -- ScoreTracker publishes nothing -- so it has no entry.

def _decode_move_started(op: list) -> MoveStarted:
    return MoveStarted(
        move_id=op[delta_ops.OP_MOVE_ID],
        piece_id=op[delta_ops.OP_PIECE_ID],
        src=Position(op[delta_ops.MOVE_STARTED_ORIGIN_X], op[delta_ops.MOVE_STARTED_ORIGIN_Y]),
        dst=Position(op[delta_ops.MOVE_STARTED_TARGET_X], op[delta_ops.MOVE_STARTED_TARGET_Y]),
        start_time_ms=op[delta_ops.MOVE_STARTED_START_MS],
        arrival_time_ms=op[delta_ops.MOVE_STARTED_ARRIVAL_MS],
    )


def _decode_move_truncated(op: list) -> MoveTruncated:
    return MoveTruncated(
        move_id=op[delta_ops.OP_MOVE_ID],
        piece_id=op[delta_ops.OP_PIECE_ID],
        target=Position(
            op[delta_ops.MOVE_TRUNCATED_TARGET_X], op[delta_ops.MOVE_TRUNCATED_TARGET_Y]
        ),
        arrival_time_ms=op[delta_ops.MOVE_TRUNCATED_ARRIVAL_MS],
        in_flight=op[delta_ops.MOVE_TRUNCATED_IN_FLIGHT],
    )


def _decode_move_completed(op: list) -> MoveCompleted:
    return MoveCompleted(
        move_id=op[delta_ops.OP_MOVE_ID],
        piece_id=op[delta_ops.OP_PIECE_ID],
        piece_type=PieceType(op[delta_ops.MOVE_COMPLETED_TYPE]),
        color=Color(op[delta_ops.MOVE_COMPLETED_COLOR]),
        src=Position(op[delta_ops.MOVE_COMPLETED_SRC_X], op[delta_ops.MOVE_COMPLETED_SRC_Y]),
        dst=Position(op[delta_ops.MOVE_COMPLETED_DST_X], op[delta_ops.MOVE_COMPLETED_DST_Y]),
    )


def _decode_move_aborted(op: list) -> MoveAborted:
    return MoveAborted(
        move_id=op[delta_ops.OP_MOVE_ID],
        piece_id=op[delta_ops.OP_PIECE_ID],
        position=Position(op[delta_ops.MOVE_ABORTED_X], op[delta_ops.MOVE_ABORTED_Y]),
    )


def _decode_piece_captured(op: list) -> PieceCaptured:
    return PieceCaptured(
        piece_id=op[delta_ops.OP_PIECE_ID],
        piece_type=PieceType(op[delta_ops.PIECE_CAPTURED_TYPE]),
        color=Color(op[delta_ops.PIECE_CAPTURED_COLOR]),
        position=Position(op[delta_ops.PIECE_CAPTURED_X], op[delta_ops.PIECE_CAPTURED_Y]),
        capturing_move_id=op[delta_ops.OP_MOVE_ID],
    )


def _decode_rest_ended(op: list) -> RestEnded:
    return RestEnded(
        piece_id=op[delta_ops.OP_PIECE_ID],
        position=Position(op[delta_ops.REST_ENDED_X], op[delta_ops.REST_ENDED_Y]),
    )


_OP_DECODERS: dict[str, Callable[[list], object]] = {
    OpCode.MOVE_STARTED.value: _decode_move_started,
    OpCode.MOVE_TRUNCATED.value: _decode_move_truncated,
    OpCode.MOVE_COMPLETED.value: _decode_move_completed,
    OpCode.MOVE_ABORTED.value: _decode_move_aborted,
    OpCode.PIECE_CAPTURED.value: _decode_piece_captured,
    OpCode.REST_ENDED.value: _decode_rest_ended,
}


def events_from_ops(ops: list[list]) -> list[object]:
    """The engine events `ops` were built from, in order. Ops with no event
    behind them, and any op code this client doesn't know, are skipped rather
    than raising -- an unrecognised op must never take the GUI down."""
    events = []
    for op in ops:
        decoder = _OP_DECODERS.get(op[delta_ops.OP_CODE_INDEX])
        if decoder is not None:
            events.append(decoder(op))
    return events


class RemoteBoardView:
    """The read-only slice of Board's API that Controller uses, backed by
    whichever game state is current."""

    def __init__(self, current_state: Callable[[], RemoteGameState]):
        self._current_state = current_state

    def is_within_boundaries(self, pos: Position) -> bool:
        return 0 <= pos.x < DEFAULT_BOARD_SIZE and 0 <= pos.y < DEFAULT_BOARD_SIZE

    def is_cell_empty(self, pos: Position) -> bool:
        return pos not in self._current_state().by_position

    def get_piece_at(self, pos: Position) -> PieceDTO | None:
        return self._current_state().by_position.get(pos)


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
    def apply_keyframe(self, payload: KeyframePayload) -> None:
        state = RemoteGameState.from_keyframe(payload)
        with self._lock:
            self._state = state

    def apply_delta(self, payload: DeltaPayload) -> None:
        """Advance the board by one frame, then republish the engine events
        the frame's ops were built from. State first: a subscriber reacting
        to an event must not see the board it describes as not yet updated."""
        with self._lock:
            self._state = self._state.apply_delta(payload)
        for event in events_from_ops(payload.ops):
            self.events.publish(event)

    def end_game(self, payload: GameOverPayload) -> None:
        self.game_active = False
        self.game_over_payload = payload
        self.events.publish(GameEnded(Color(payload.winner)))
