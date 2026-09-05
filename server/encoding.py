"""Encoding of server-side game state into wire frames.

`shared/messages.py` deliberately knows nothing about `game_engine` or
`events`, so both encoding directions live here, on the only side that has a
real engine to encode:

- `keyframe_payload_from_snapshot` - a whole GameSnapshot, the recovery path.
- `op_from_event` - one engine event as one positional-array delta op (see
  `shared/delta_ops.py` for the layout). `server/delta.py` buffers these into
  frames; this module only knows how to shape one.
"""

from game_engine.snapshot import GameSnapshot
from events.game_events import (
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)
from model.piece import Color
from shared.delta_ops import OpCode
from shared.messages import KeyframePayload, PiecePayload


def keyframe_payload_from_snapshot(snapshot: GameSnapshot) -> KeyframePayload:
    return KeyframePayload(
        pieces=[PiecePayload.from_piece_dto(piece) for piece in snapshot.get_all_pieces()],
        scores={color.value: score for color, score in snapshot.get_scores().items()},
        server_time_ms=snapshot.get_clock_ms(),
    )


def _encode_move_started(event: MoveStarted) -> list:
    return [
        OpCode.MOVE_STARTED.value, event.piece_id, event.move_id,
        event.src.x, event.src.y, event.dst.x, event.dst.y,
        event.start_time_ms, event.arrival_time_ms,
    ]


def _encode_move_truncated(event: MoveTruncated) -> list:
    return [
        OpCode.MOVE_TRUNCATED.value, event.piece_id, event.move_id,
        event.target.x, event.target.y,
        event.arrival_time_ms, event.in_flight,
    ]


def _encode_move_completed(event: MoveCompleted) -> list:
    return [
        OpCode.MOVE_COMPLETED.value, event.piece_id, event.move_id,
        event.src.x, event.src.y, event.dst.x, event.dst.y,
        event.piece_type.value, event.color.value,
    ]


def _encode_move_aborted(event: MoveAborted) -> list:
    return [
        OpCode.MOVE_ABORTED.value, event.piece_id, event.move_id,
        event.position.x, event.position.y,
    ]


def _encode_piece_captured(event: PieceCaptured) -> list:
    return [
        OpCode.PIECE_CAPTURED.value, event.piece_id, event.capturing_move_id,
        event.position.x, event.position.y,
        event.piece_type.value, event.color.value,
    ]


def _encode_rest_ended(event: RestEnded) -> list:
    return [
        OpCode.REST_ENDED.value, event.piece_id,
        event.position.x, event.position.y,
    ]


_OP_ENCODERS = {
    MoveStarted: _encode_move_started,
    MoveTruncated: _encode_move_truncated,
    MoveCompleted: _encode_move_completed,
    MoveAborted: _encode_move_aborted,
    PieceCaptured: _encode_piece_captured,
    RestEnded: _encode_rest_ended,
}


def op_from_event(event) -> list | None:
    """The delta op for `event`, or None for an event that carries no board
    change of its own (GameStarted, and GameEnded - which GAME_OVER already
    reports)."""
    encoder = _OP_ENCODERS.get(type(event))
    return None if encoder is None else encoder(event)


def scores_op(scores: dict[Color, int]) -> list:
    return [OpCode.SCORES.value, scores[Color.WHITE], scores[Color.BLACK]]
