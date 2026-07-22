from server.connection import Connection
from server.dispatcher import register
from server.protocol import Envelope, MessageType
from server.session import PlayerSession


@register(MessageType.AUTH)
async def handle_auth(conn: Connection, envelope: Envelope) -> None:
    player_id = envelope.payload.get("player_id")
    if not player_id:
        await conn.send_error("auth payload requires player_id")
        return
    PlayerSession(player_id, conn)
    await conn.send(Envelope(type=MessageType.AUTH, payload={"status": "ok", "player_id": player_id}))
