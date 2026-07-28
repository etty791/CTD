import asyncio

from pydantic import ValidationError

from server.connection import Connection
from server.dispatcher import register
from server.encoding import state_payload_from_snapshot
from server.game_registry import GameRegistry
from server.game_session import GameSession
from shared.messages import (
    AuthAckPayload,
    CredentialsPayload,
    GameStartPayload,
    JoinRoomPayload,
    JumpPayload,
    MovePayload,
    RoomWaitingPayload,
)
from shared.protocol import Envelope, MessageType
from server.rooms import Room, RoomManager
from server.async_clock import AsyncClock
from server.persistence.worker import PersistenceWorker
from server.server_config import (
    ERROR_ACCOUNT_NOT_FOUND,
    ERROR_ALREADY_IN_GAME,
    ERROR_ALREADY_LOGGED_IN,
    ERROR_BAD_CREDENTIALS,
    ERROR_ILLEGAL_MOVE,
    ERROR_NOT_AUTHENTICATED,
    ERROR_NOT_IN_GAME,
    ERROR_NOT_YOUR_PIECE,
    ERROR_NO_MATCH_FOUND,
    ERROR_OBSERVER_CANNOT_MOVE,
    ERROR_ROOM_NOT_FOUND,
    ERROR_USERNAME_TAKEN,
    TICK_MS,
)
from shared.protocol_config import MATCH_TIMEOUT_MS, ROOM_STATUS_WAITING, Role, Status
from server.session import PlayerSession
from model.piece import Color

registry = GameRegistry()
room_manager = RoomManager()
clock = AsyncClock(TICK_MS)
persistence = PersistenceWorker()
logged_in_usernames: set[str] = set()


# --- shared helpers (not registered as message handlers) -------------------

async def _start_game_from_room(room: Room) -> None:
    """Called once a room/seek has just filled both seats."""
    player_a, player_b = room.players[0], room.players[1]
    game = registry.create_game(
        player_a, player_b, clock, persistence, room.name, on_finalize=_on_game_finalized
    )
    room.game_id = game.id
    for player_id, session in game.players.items():
        color = game.color_of[player_id]
        await session.connection.send(
            Envelope(
                type=MessageType.GAME_START,
                payload=GameStartPayload(
                    game_id=game.id,
                    role=Role.PLAYER.value,
                    color=color.value,
                    white_username=player_a.player_id,
                    black_username=player_b.player_id,
                ).model_dump(),
                game_id=game.id,
            )
        )
    await game.broadcast_state()


async def _on_game_finalized(game: GameSession) -> None:
    """GameSession.on_finalize callback: drop the game and free every
    participant's room membership -- players and observers alike, so a
    finished game's room closes once everyone has left it instead of
    leaving a spectator wedged in a dead room."""
    registry.remove(game.id)
    for session in (*game.players.values(), *game.observers):
        room_manager.leave(session)


def _on_seek_timeout(session: PlayerSession) -> None:
    # Sync: AsyncClock.after's callback contract is Callable[[], None].
    # cancel_seek returns False (harmless no-op) if the session was already
    # matched and removed from the pool by the time this fires.
    if room_manager.cancel_seek(session):
        asyncio.create_task(session.connection.send_error(ERROR_NO_MATCH_FOUND))


def _already_seated(player_id: str) -> bool:
    return (
        room_manager.room_of(player_id) is not None
        or registry.get_game_for_player(player_id) is not None
    )


# --- auth --------------------------------------------------------------

@register(MessageType.REGISTER)
async def handle_register(conn: Connection, envelope: Envelope) -> None:
    try:
        payload = CredentialsPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    result = await asyncio.wrap_future(
        persistence.submit(lambda repo: repo.create_user(payload.username, payload.password))
    )
    if not result.ok:
        await conn.send_error(ERROR_USERNAME_TAKEN)
        return

    # Registering does not log in.
    await conn.send(
        Envelope(
            type=MessageType.REGISTER,
            payload=AuthAckPayload(
                status=Status.OK, player_id=payload.username, rating=None
            ).model_dump(),
        )
    )


@register(MessageType.LOGIN)
async def handle_login(conn: Connection, envelope: Envelope) -> None:
    try:
        payload = CredentialsPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    if conn.player_session is not None or payload.username in logged_in_usernames:
        await conn.send_error(ERROR_ALREADY_LOGGED_IN)
        return

    result = await asyncio.wrap_future(
        persistence.submit(lambda repo: repo.authenticate(payload.username, payload.password))
    )
    if not result.ok:
        # Don't distinguish no-such-user from bad-password: avoid username enumeration.
        await conn.send_error(ERROR_BAD_CREDENTIALS)
        return

    PlayerSession(payload.username, conn)
    logged_in_usernames.add(payload.username)
    await conn.send(
        Envelope(
            type=MessageType.LOGIN,
            payload=AuthAckPayload(
                status=Status.OK, player_id=payload.username, rating=result.rating
            ).model_dump(),
        )
    )


# --- rooms / matchmaking -------------------------------------------------

@register(MessageType.CREATE_ROOM)
async def handle_create_room(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return
    session = conn.player_session

    if _already_seated(session.player_id):
        await conn.send_error(ERROR_ALREADY_IN_GAME)
        return

    result = room_manager.create_room(session)
    await conn.send(
        Envelope(
            type=MessageType.CREATE_ROOM,
            payload=RoomWaitingPayload(
                room_id=result.room.name, status=ROOM_STATUS_WAITING
            ).model_dump(),
        )
    )


@register(MessageType.JOIN_ROOM)
async def handle_join_room(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return
    session = conn.player_session

    try:
        payload = JoinRoomPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    if _already_seated(session.player_id):
        await conn.send_error(ERROR_ALREADY_IN_GAME)
        return

    if not room_manager.room_exists(payload.room_id):
        await conn.send_error(ERROR_ROOM_NOT_FOUND)
        return

    result = room_manager.join(payload.room_id, session)

    if result.should_start_game:
        await _start_game_from_room(result.room)
        return

    if result.role == Role.OBSERVER:
        game = registry.get(result.room.game_id) if result.room.game_id else None
        if game is None:
            # Inconsistent-state edge case: room marked live but no game found.
            await conn.send_error(ERROR_NOT_IN_GAME)
            return

        game.add_observer(session)
        registry.add_observer(game.id, session.player_id)
        await conn.send(
            Envelope(
                type=MessageType.GAME_START,
                payload=GameStartPayload(
                    game_id=game.id,
                    role=Role.OBSERVER.value,
                    color=None,
                    white_username=game.username_of_color(Color.WHITE),
                    black_username=game.username_of_color(Color.BLACK),
                ).model_dump(),
                game_id=game.id,
            )
        )
        # Personal snapshot, not a broadcast -- otherwise they'd wait up to
        # TICK_MS for the next tick to see the board.
        state_payload = state_payload_from_snapshot(game.engine.get_snapshot())
        await conn.send(
            Envelope(
                type=MessageType.STATE,
                payload=state_payload.model_dump(),
                game_id=game.id,
            )
        )
        return

    # role == PLAYER, not yet started: only the first seat of an existing
    # empty room got filled. In practice create_room already seats the
    # creator immediately, so this is mostly theoretical -- must not crash.
    await conn.send(
        Envelope(
            type=MessageType.JOIN_ROOM,
            payload=RoomWaitingPayload(
                room_id=result.room.name, status=ROOM_STATUS_WAITING
            ).model_dump(),
        )
    )


@register(MessageType.PLAY)
async def handle_play(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return
    session = conn.player_session

    if _already_seated(session.player_id):
        await conn.send_error(ERROR_ALREADY_IN_GAME)
        return

    rating = await asyncio.wrap_future(
        persistence.submit(lambda repo: repo.get_rating(session.player_id))
    )
    if rating is None:
        await conn.send_error(ERROR_ACCOUNT_NOT_FOUND)
        return

    result = room_manager.seek(session, rating)
    if result.matched:
        await _start_game_from_room(result.room)
        return

    clock.after(MATCH_TIMEOUT_MS, lambda: _on_seek_timeout(session))


# --- in-game moves ---------------------------------------------------------

@register(MessageType.MOVE)
async def handle_move(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return

    player_id = conn.player_session.player_id
    game = registry.get_game_for_player(player_id)
    if game is None:
        await conn.send_error(ERROR_NOT_IN_GAME)
        return

    if player_id not in game.color_of:
        await conn.send_error(ERROR_OBSERVER_CANNOT_MOVE)
        return

    try:
        move_payload = MovePayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    origin = move_payload.from_.to_position()
    target = move_payload.to.to_position()

    piece_color = game.engine.piece_color_at(origin)
    if piece_color is not None and piece_color != game.color_of[player_id]:
        await conn.send_error(ERROR_NOT_YOUR_PIECE)
        return

    validation = game.engine.move_request(origin, target)
    if not validation.is_valid:
        await conn.send_error(ERROR_ILLEGAL_MOVE.format(reason=validation.reason))
        return

    await game.broadcast_state()


@register(MessageType.JUMP)
async def handle_jump(conn: Connection, envelope: Envelope) -> None:
    if conn.player_session is None:
        await conn.send_error(ERROR_NOT_AUTHENTICATED)
        return

    player_id = conn.player_session.player_id
    game = registry.get_game_for_player(player_id)
    if game is None:
        await conn.send_error(ERROR_NOT_IN_GAME)
        return

    if player_id not in game.color_of:
        await conn.send_error(ERROR_OBSERVER_CANNOT_MOVE)
        return

    try:
        jump_payload = JumpPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        await conn.send_error(str(exc))
        return

    pos = jump_payload.pos.to_position()
    piece_color = game.engine.piece_color_at(pos)
    if piece_color is not None and piece_color != game.color_of[player_id]:
        await conn.send_error(ERROR_NOT_YOUR_PIECE)
        return

    validation = game.engine.jump_request(pos)
    if not validation.is_valid:
        await conn.send_error(ERROR_ILLEGAL_MOVE.format(reason=validation.reason))
        return

    await game.broadcast_state()
