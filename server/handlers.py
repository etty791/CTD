from typing import Optional

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
