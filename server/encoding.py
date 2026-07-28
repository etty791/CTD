"""Encoding of server-side game state into wire payloads.

`shared/messages.py` deliberately knows nothing about `game_engine`, so the
GameSnapshot -> StatePayload direction lives here, on the only side that has
a real engine to encode.
"""

from game_engine.snapshot import GameSnapshot
from shared.messages import PiecePayload, StatePayload


def state_payload_from_snapshot(snapshot: GameSnapshot) -> StatePayload:
    return StatePayload(
        pieces=[PiecePayload.from_piece_dto(piece) for piece in snapshot.get_all_pieces()],
        scores={color.value: score for color, score in snapshot.get_scores().items()},
        server_time_ms=snapshot.get_clock_ms(),
    )
