"""Encoding of server-side game state into wire payloads.

`shared/messages.py` deliberately knows nothing about `game_engine`, so the
GameSnapshot -> StatePayload direction lives here, on the only side that has
a real engine to encode.
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
from shared.messages import EventPayload, PiecePayload, PositionPayload, StatePayload


def state_payload_from_snapshot(snapshot: GameSnapshot) -> StatePayload:
    return StatePayload(
        pieces=[PiecePayload.from_piece_dto(piece) for piece in snapshot.get_all_pieces()],
        scores={color.value: score for color, score in snapshot.get_scores().items()},
        server_time_ms=snapshot.get_clock_ms(),
    )


def _encode_move_started(event: MoveStarted) -> dict:
    return {
        "move_id": event.move_id,
        "piece_id": event.piece_id,
        "src": PositionPayload.from_position(event.src).model_dump(),
        "dst": PositionPayload.from_position(event.dst).model_dump(),
    }


def _encode_move_completed(event: MoveCompleted) -> dict:
    return {
        "move_id": event.move_id,
        "piece_id": event.piece_id,
        "piece_type": event.piece_type.value,
        "color": event.color.value,
        "src": PositionPayload.from_position(event.src).model_dump(),
        "dst": PositionPayload.from_position(event.dst).model_dump(),
    }


def _encode_move_truncated(event: MoveTruncated) -> dict:
    return {
        "move_id": event.move_id,
        "piece_id": event.piece_id,
        "target": PositionPayload.from_position(event.target).model_dump(),
        "arrival_time_ms": event.arrival_time_ms,
    }


def _encode_move_aborted(event: MoveAborted) -> dict:
    return {
        "move_id": event.move_id,
        "piece_id": event.piece_id,
        "position": PositionPayload.from_position(event.position).model_dump(),
    }


def _encode_piece_captured(event: PieceCaptured) -> dict:
    return {
        "piece_id": event.piece_id,
        "piece_type": event.piece_type.value,
        "color": event.color.value,
        "position": PositionPayload.from_position(event.position).model_dump(),
        "capturing_move_id": event.capturing_move_id,
    }


def _encode_rest_ended(event: RestEnded) -> dict:
    return {
        "piece_id": event.piece_id,
        "position": PositionPayload.from_position(event.position).model_dump(),
    }


_EVENT_ENCODERS = {
    MoveStarted: _encode_move_started,
    MoveCompleted: _encode_move_completed,
    MoveTruncated: _encode_move_truncated,
    MoveAborted: _encode_move_aborted,
    PieceCaptured: _encode_piece_captured,
    RestEnded: _encode_rest_ended,
}


def event_payload_from(event) -> EventPayload:
    encoder = _EVENT_ENCODERS[type(event)]
    return EventPayload(event_type=type(event).__name__, data=encoder(event))
