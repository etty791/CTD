from typing import Optional

from pydantic import ValidationError

from server.connection import Connection
from server.dispatcher import register
from server.game_registry import GameRegistry
from server.messages import AuthAckPayload, AuthPayload, MovePayload
from server.protocol import Envelope, MessageType
from server.server_config import (
    AUTH_STATUS_OK,
    ERROR_ILLEGAL_MOVE,
    ERROR_NOT_AUTHENTICATED,
    ERROR_NOT_IN_GAME,
    ERROR_NOT_YOUR_PIECE,
)
from server.session import PlayerSession

registry = GameRegistry()
_waiting_player: Optional[PlayerSession] = None


@register(MessageType.AUTH)
async def handle_auth(conn: Connection, envelope: Envelope) -> None:
    global _waiting_player

    try:
        auth_payload = AuthPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    session = PlayerSession(auth_payload.player_id, conn)
    await conn.send(Envelope(
        type=MessageType.AUTH,
        payload=AuthAckPayload(status=AUTH_STATUS_OK, player_id=auth_payload.player_id).model_dump(),
    ))

    if _waiting_player is None:
        _waiting_player = session
        return

    game = registry.create_game(_waiting_player, session)
    _waiting_player = None
    await game.broadcast_state()


#TODO: wrong seperation, not supposed to check is cell empty etc
@register(MessageType.MOVE)
async def handle_move(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return

    game = registry.get_game_for_player(conn.player_session.player_id)
    if game is None:
        await conn.send_error(ERROR_NOT_IN_GAME)
        return

    try:
        move_payload = MovePayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    origin = move_payload.from_.to_position()
    target = move_payload.to.to_position()

    player_id = conn.player_session.player_id
    if not game.engine.board.is_cell_empty(origin):
        piece_color = game.engine.board.get_piece_at(origin).color
        if piece_color != game.color_of[player_id]:
            await conn.send_error(ERROR_NOT_YOUR_PIECE)
            return

    validation = game.engine.move_request(origin, target)
    if not validation.is_valid:
        await conn.send_error(ERROR_ILLEGAL_MOVE.format(reason=validation.reason))
        return

    await game.broadcast_state()
