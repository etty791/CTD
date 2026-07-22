from typing import Optional

from model.position import Position
from server.connection import Connection
from server.dispatcher import register
from server.game_registry import GameRegistry
from server.protocol import Envelope, MessageType
from server.session import PlayerSession

registry = GameRegistry()
_waiting_player: Optional[PlayerSession] = None


@register(MessageType.AUTH)
async def handle_auth(conn: Connection, envelope: Envelope) -> None:
    global _waiting_player

    player_id = envelope.payload.get("player_id")
    if not player_id:
        await conn.send_error("auth payload requires player_id")
        return
    session = PlayerSession(player_id, conn)
    await conn.send(Envelope(type=MessageType.AUTH, payload={"status": "ok", "player_id": player_id}))

    if _waiting_player is None:
        _waiting_player = session
        return

    game = registry.create_game(_waiting_player, session)
    _waiting_player = None
    await game.broadcast_state()


def _position_from_dict(raw: dict) -> Optional[Position]:
    if "x" not in raw or "y" not in raw:
        return None
    return Position(raw["x"], raw["y"])


@register(MessageType.MOVE)
async def handle_move(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error("not authenticated")
        return

    game = registry.get_game_for_player(conn.player_session.player_id)
    if game is None:
        await conn.send_error("not in a game")
        return

    origin = _position_from_dict(envelope.payload.get("from", {}))
    target = _position_from_dict(envelope.payload.get("to", {}))
    if origin is None or target is None:
        await conn.send_error("move payload requires from={x,y} and to={x,y}")
        return

    player_id = conn.player_session.player_id
    if not game.engine.board.is_cell_empty(origin):
        piece_color = game.engine.board.get_piece_at(origin).color
        if piece_color != game.color_of[player_id]:
            await conn.send_error("not your piece")
            return

    validation = game.engine.move_request(origin, target)
    if not validation.is_valid:
        await conn.send_error(f"illegal move: {validation.reason}")
        return

    await game.broadcast_state()
