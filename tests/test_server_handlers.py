import asyncio
from concurrent.futures import Future

import pytest

from model.piece import Color
from server import handlers
from server.game_registry import GameRegistry
from server.persistence.db import Database
from server.persistence.user_repository import GameResultRatings, UserRepository
from shared.protocol import Envelope, MessageType
from server.rooms import RoomManager
from server.server_config import (
    ERROR_ACCOUNT_NOT_FOUND,
    ERROR_ALREADY_IN_GAME,
    ERROR_ALREADY_LOGGED_IN,
    ERROR_BAD_CREDENTIALS,
    ERROR_NOT_AUTHENTICATED,
    ERROR_NOT_IN_GAME,
    ERROR_NOT_YOUR_PIECE,
    ERROR_NO_MATCH_FOUND,
    ERROR_OBSERVER_CANNOT_MOVE,
    ERROR_OBSERVER_CANNOT_RESIGN,
    ERROR_ROOM_NOT_FOUND,
    ERROR_USERNAME_TAKEN,
    GAME_OVER_REASON_DISCONNECT,
    GAME_OVER_REASON_RESIGNATION,
)
from shared.protocol_config import ROOM_STATUS_WAITING
from server.session import PlayerSession


class FakeConnection:
    def __init__(self):
        self.player_session = None
        self.sent: list[Envelope] = []
        self.errors: list[str] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    async def send_raw(self, body: str, message_type) -> None:
        await self.send(Envelope.model_validate_json(body))

    async def send_error(self, message: str) -> None:
        self.errors.append(message)
        await self.send(Envelope(type=MessageType.ERROR, payload={"message": message}))


class _FakeHandle:
    def __init__(self):
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeClock:
    """Records the tick callback (.every) and any .after(delay, cb) requests
    without spawning a real asyncio loop or auto-firing timeouts. Tests fire
    a recorded .after callback manually via `clock.after_calls[-1][1]()`.
    `now_ms` is a plain settable attribute so tests control matchmaking's
    widening-band time without touching a real clock."""

    def __init__(self):
        self.callback = None
        self.after_calls: list[tuple[int, object]] = []
        self._now_ms = 0

    def every(self, callback):
        self.callback = callback
        return _FakeHandle()

    def after(self, delay_ms, callback):
        self.after_calls.append((delay_ms, callback))
        return _FakeHandle()

    def now_ms(self):
        return self._now_ms


class _InertPersistence:
    """Default placeholder: submit(fn) never runs fn, resolves to None.
    Fine for tests that build games but never touch persistence directly
    (move/jump wiring). Swapped out for RealPersistence/_CannedPersistence
    wherever a test actually needs repository behavior or Elo results."""

    def submit(self, fn):
        future: Future = Future()
        future.set_result(None)
        return future


class _CannedPersistence:
    """Returns a preset GameResultRatings without running fn -- for tests
    that only need finalize's Elo-consuming plumbing to work, not real Elo
    math (that's covered by tests/test_game_session.py)."""

    def __init__(self, ratings: GameResultRatings | None = None):
        self._ratings = ratings or GameResultRatings(
            white_old=1200, white_new=1216, black_old=1200, black_new=1184
        )

    def submit(self, fn):
        future: Future = Future()
        future.set_result(self._ratings)
        return future


class _RealPersistence:
    """submit(fn) actually executes fn against a real UserRepository backed
    by a tmp_path sqlite Database -- for register/login/play tests that
    exercise real create_user/authenticate/get_rating behavior."""

    def __init__(self, repo: UserRepository):
        self.repo = repo

    def submit(self, fn):
        future: Future = Future()
        try:
            future.set_result(fn(self.repo))
        except Exception as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        return future


@pytest.fixture
def real_persistence(tmp_path):
    db = Database(str(tmp_path / "handlers_test.db"))
    db.init_schema()
    return _RealPersistence(UserRepository(db))


def _create_test_game(player_a, player_b, persistence=None):
    return handlers.registry.create_game(
        player_a,
        player_b,
        handlers.clock,
        persistence or handlers.persistence,
        room_id="r1",
    )


async def flush_tasks():
    """Deterministically run every task scheduled via create_task to completion."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


@pytest.fixture(autouse=True)
def reset_handler_state():
    """handlers.* are module-level singletons; give each test a clean slate."""
    handlers.registry = GameRegistry()
    handlers.room_manager = RoomManager()
    handlers.clock = _FakeClock()
    handlers.persistence = _InertPersistence()
    handlers.logged_in_usernames = set()
    handlers._pending_seek_timers = {}
    yield
    handlers.registry = GameRegistry()
    handlers.room_manager = RoomManager()
    handlers.clock = _FakeClock()
    handlers.persistence = _InertPersistence()
    handlers.logged_in_usernames = set()
    handlers._pending_seek_timers = {}


class TestHandleRegister:
    async def test_success_acks_without_rating(self, real_persistence):
        handlers.persistence = real_persistence
        conn = FakeConnection()
        envelope = Envelope(
            type=MessageType.REGISTER, payload={"username": "alice", "password": "pw"}
        )

        await handlers.handle_register(conn, envelope)

        assert conn.errors == []
        assert conn.sent[-1].type == MessageType.REGISTER
        assert conn.sent[-1].payload == {"status": "ok", "player_id": "alice", "rating": None}
        # registering does not log in
        assert conn.player_session is None

    async def test_duplicate_username_errors(self, real_persistence):
        handlers.persistence = real_persistence
        envelope = Envelope(
            type=MessageType.REGISTER, payload={"username": "alice", "password": "pw"}
        )
        await handlers.handle_register(FakeConnection(), envelope)

        conn2 = FakeConnection()
        await handlers.handle_register(conn2, envelope)

        assert conn2.errors == [ERROR_USERNAME_TAKEN]


class TestHandleLogin:
    async def test_success_acks_with_rating(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        envelope = Envelope(
            type=MessageType.LOGIN, payload={"username": "alice", "password": "pw"}
        )

        await handlers.handle_login(conn, envelope)

        assert conn.errors == []
        assert conn.sent[-1].type == MessageType.LOGIN
        assert conn.sent[-1].payload["status"] == "ok"
        assert conn.sent[-1].payload["rating"] == 1200
        assert conn.player_session is not None
        assert "alice" in handlers.logged_in_usernames

    async def test_bad_password_errors(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        envelope = Envelope(
            type=MessageType.LOGIN, payload={"username": "alice", "password": "wrong"}
        )

        await handlers.handle_login(conn, envelope)

        assert conn.errors == [ERROR_BAD_CREDENTIALS]
        assert conn.player_session is None

    async def test_double_login_same_connection_errors(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        envelope = Envelope(
            type=MessageType.LOGIN, payload={"username": "alice", "password": "pw"}
        )
        await handlers.handle_login(conn, envelope)

        await handlers.handle_login(conn, envelope)

        assert conn.errors == [ERROR_ALREADY_LOGGED_IN]

    async def test_double_login_different_connection_errors(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        envelope = Envelope(
            type=MessageType.LOGIN, payload={"username": "alice", "password": "pw"}
        )
        await handlers.handle_login(FakeConnection(), envelope)

        conn2 = FakeConnection()
        await handlers.handle_login(conn2, envelope)

        assert conn2.errors == [ERROR_ALREADY_LOGGED_IN]


class TestHandleCreateRoom:
    async def test_ack_has_room_id_and_waiting_status(self):
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_create_room(conn, Envelope(type=MessageType.CREATE_ROOM, payload={}))

        envelope = conn.sent[-1]
        assert envelope.type == MessageType.CREATE_ROOM
        assert envelope.payload["status"] == ROOM_STATUS_WAITING
        assert envelope.payload["room_id"]

    async def test_already_in_room_errors(self):
        conn = FakeConnection()
        PlayerSession("alice", conn)
        await handlers.handle_create_room(conn, Envelope(type=MessageType.CREATE_ROOM, payload={}))

        await handlers.handle_create_room(conn, Envelope(type=MessageType.CREATE_ROOM, payload={}))

        assert conn.errors == [ERROR_ALREADY_IN_GAME]


class TestHandleJoinRoom:
    async def test_second_joiner_starts_game_with_keyframe(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)

        await handlers.handle_create_room(conn_a, Envelope(type=MessageType.CREATE_ROOM, payload={}))
        room_id = conn_a.sent[-1].payload["room_id"]

        await handlers.handle_join_room(
            conn_b, Envelope(type=MessageType.JOIN_ROOM, payload={"room_id": room_id})
        )

        start_a = [e for e in conn_a.sent if e.type == MessageType.GAME_START]
        start_b = [e for e in conn_b.sent if e.type == MessageType.GAME_START]
        assert len(start_a) == 1 and len(start_b) == 1
        assert start_a[0].payload["color"] == "w"
        assert start_b[0].payload["color"] == "b"
        assert start_a[0].payload["game_id"] == start_b[0].payload["game_id"]
        assert any(e.type == MessageType.KEYFRAME for e in conn_a.sent)
        assert any(e.type == MessageType.KEYFRAME for e in conn_b.sent)

    async def test_unknown_room_id_errors(self):
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_join_room(
            conn, Envelope(type=MessageType.JOIN_ROOM, payload={"room_id": "NOPE12"})
        )

        assert conn.errors == [ERROR_ROOM_NOT_FOUND]

    async def test_already_in_room_errors(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)
        await handlers.handle_create_room(conn_a, Envelope(type=MessageType.CREATE_ROOM, payload={}))
        room_id = conn_a.sent[-1].payload["room_id"]

        await handlers.handle_join_room(
            conn_a, Envelope(type=MessageType.JOIN_ROOM, payload={"room_id": room_id})
        )

        assert conn_a.errors == [ERROR_ALREADY_IN_GAME]

    async def test_third_joiner_becomes_observer_with_personal_envelopes(self):
        conn_a, conn_b, conn_c = FakeConnection(), FakeConnection(), FakeConnection()
        PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)
        PlayerSession("carol", conn_c)

        await handlers.handle_create_room(conn_a, Envelope(type=MessageType.CREATE_ROOM, payload={}))
        room_id = conn_a.sent[-1].payload["room_id"]
        await handlers.handle_join_room(
            conn_b, Envelope(type=MessageType.JOIN_ROOM, payload={"room_id": room_id})
        )
        sent_a_before = len(conn_a.sent)
        sent_b_before = len(conn_b.sent)

        await handlers.handle_join_room(
            conn_c, Envelope(type=MessageType.JOIN_ROOM, payload={"room_id": room_id})
        )

        start_c = [e for e in conn_c.sent if e.type == MessageType.GAME_START]
        assert len(start_c) == 1
        assert start_c[0].payload["role"] == "observer"
        assert start_c[0].payload["color"] is None
        assert any(e.type == MessageType.KEYFRAME for e in conn_c.sent)
        # observer's personal join must not broadcast to the existing players
        assert len(conn_a.sent) == sent_a_before
        assert len(conn_b.sent) == sent_b_before


class TestHandlePlay:
    async def test_two_compatible_ratings_get_matched(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        real_persistence.repo.create_user("bob", "pw")
        conn_a, conn_b = FakeConnection(), FakeConnection()
        PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)

        await handlers.handle_play(conn_a, Envelope(type=MessageType.PLAY, payload={}))
        await handlers.handle_play(conn_b, Envelope(type=MessageType.PLAY, payload={}))

        start_a = [e for e in conn_a.sent if e.type == MessageType.GAME_START]
        start_b = [e for e in conn_b.sent if e.type == MessageType.GAME_START]
        assert len(start_a) == 1 and len(start_b) == 1
        assert start_a[0].payload["color"] == "w"  # first caller = White
        assert start_b[0].payload["color"] == "b"  # second caller = Black

    async def test_missing_rating_row_errors_instead_of_crashing(self, real_persistence):
        handlers.persistence = real_persistence
        # No create_user call: "alice" has a session but no row in the
        # users table, so get_rating returns None (deleted account, etc).
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_play(conn, Envelope(type=MessageType.PLAY, payload={}))

        assert conn.errors == [ERROR_ACCOUNT_NOT_FOUND]
        assert not any(e.type == MessageType.GAME_START for e in conn.sent)

    async def test_lone_seeker_times_out(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_play(conn, Envelope(type=MessageType.PLAY, payload={}))
        assert len(handlers.clock.after_calls) == 1

        _, callback = handlers.clock.after_calls[0]
        callback()
        await flush_tasks()

        assert conn.errors == [ERROR_NO_MATCH_FOUND]

    async def test_matched_seeker_ignores_stale_timeout(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        real_persistence.repo.create_user("bob", "pw")
        conn_a, conn_b = FakeConnection(), FakeConnection()
        PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)

        await handlers.handle_play(conn_a, Envelope(type=MessageType.PLAY, payload={}))
        _, stale_callback = handlers.clock.after_calls[0]

        await handlers.handle_play(conn_b, Envelope(type=MessageType.PLAY, payload={}))

        stale_callback()
        await flush_tasks()

        assert conn_a.errors == []

    async def test_no_match_sends_queued_ack_before_scheduling_timeout(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_play(conn, Envelope(type=MessageType.PLAY, payload={}))

        play_acks = [e for e in conn.sent if e.type == MessageType.PLAY]
        assert len(play_acks) == 1
        assert play_acks[0].payload == {}
        assert len(handlers.clock.after_calls) == 1
        assert "alice" in handlers._pending_seek_timers


class TestHandleCancelSeek:
    async def test_not_authenticated_sends_error(self):
        conn = FakeConnection()
        await handlers.handle_cancel_seek(conn, Envelope(type=MessageType.CANCEL_SEEK, payload={}))

        assert conn.errors == [ERROR_NOT_AUTHENTICATED]

    async def test_cancels_pending_timer_and_seek_and_acks(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        real_persistence.repo.create_user("bob", "pw")
        conn_a, conn_b = FakeConnection(), FakeConnection()
        session_a = PlayerSession("alice", conn_a)
        PlayerSession("bob", conn_b)

        await handlers.handle_play(conn_a, Envelope(type=MessageType.PLAY, payload={}))
        timer = handlers._pending_seek_timers["alice"]

        await handlers.handle_cancel_seek(
            conn_a, Envelope(type=MessageType.CANCEL_SEEK, payload={})
        )

        assert timer.cancelled is True
        assert "alice" not in handlers._pending_seek_timers
        assert any(e.type == MessageType.CANCEL_SEEK for e in conn_a.sent)

        # alice is no longer in the seek pool: bob's play() finds no match either.
        await handlers.handle_play(conn_b, Envelope(type=MessageType.PLAY, payload={}))
        assert not any(e.type == MessageType.GAME_START for e in conn_b.sent)

    async def test_cancel_when_not_seeking_still_acks(self, real_persistence):
        handlers.persistence = real_persistence
        real_persistence.repo.create_user("alice", "pw")
        conn = FakeConnection()
        PlayerSession("alice", conn)

        await handlers.handle_cancel_seek(conn, Envelope(type=MessageType.CANCEL_SEEK, payload={}))

        assert any(e.type == MessageType.CANCEL_SEEK for e in conn.sent)
        assert conn.errors == []


class TestHandleMove:
    async def test_not_authenticated_sends_error(self):
        conn = FakeConnection()
        envelope = Envelope(type=MessageType.MOVE, payload={
            "from": {"x": 0, "y": 0}, "to": {"x": 1, "y": 0},
        })

        await handlers.handle_move(conn, envelope)

        assert conn.errors == ["not authenticated"]

    async def test_not_in_a_game_sends_error(self):
        conn = FakeConnection()
        PlayerSession("p1", conn)
        envelope = Envelope(type=MessageType.MOVE, payload={
            "from": {"x": 0, "y": 0}, "to": {"x": 1, "y": 0},
        })

        await handlers.handle_move(conn, envelope)

        assert conn.errors == ["not in a game"]

    async def test_missing_to_key_sends_validation_error(self):
        conn = FakeConnection()
        player_a = PlayerSession("p1", conn)
        player_b = PlayerSession("p2", FakeConnection())
        _create_test_game(player_a, player_b)
        envelope = Envelope(type=MessageType.MOVE, payload={"from": {"x": 0, "y": 0}})

        await handlers.handle_move(conn, envelope)

        assert len(conn.errors) == 1
        assert conn.sent[-1].type == MessageType.ERROR

    async def test_missing_from_key_sends_validation_error(self):
        conn = FakeConnection()
        player_a = PlayerSession("p1", conn)
        player_b = PlayerSession("p2", FakeConnection())
        _create_test_game(player_a, player_b)
        envelope = Envelope(type=MessageType.MOVE, payload={"to": {"x": 0, "y": 0}})

        await handlers.handle_move(conn, envelope)

        assert len(conn.errors) == 1
        assert conn.sent[-1].type == MessageType.ERROR

    async def test_observer_cannot_move(self):
        conn_a, conn_b, conn_obs = FakeConnection(), FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        game = _create_test_game(player_a, player_b)
        observer = PlayerSession("obs", conn_obs)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        envelope = Envelope(
            type=MessageType.MOVE, payload={"from": {"x": 6, "y": 0}, "to": {"x": 5, "y": 0}}
        )
        await handlers.handle_move(conn_obs, envelope)

        assert conn_obs.errors == [ERROR_OBSERVER_CANNOT_MOVE]

    async def test_wrong_owner_move_errors(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b)

        # black pawn at (1, 0); White (p1) tries to move it
        envelope = Envelope(
            type=MessageType.MOVE, payload={"from": {"x": 1, "y": 0}, "to": {"x": 2, "y": 0}}
        )
        await handlers.handle_move(conn_a, envelope)

        assert conn_a.errors == [ERROR_NOT_YOUR_PIECE]

    async def test_valid_move_broadcasts_a_delta(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b)

        envelope = Envelope(
            type=MessageType.MOVE, payload={"from": {"x": 6, "y": 0}, "to": {"x": 5, "y": 0}}
        )
        await handlers.handle_move(conn_a, envelope)

        assert conn_a.errors == []
        assert any(e.type == MessageType.DELTA for e in conn_a.sent)
        assert any(e.type == MessageType.DELTA for e in conn_b.sent)


class TestHandleResync:
    """A client that spotted a gap in Envelope.seq gets re-seeded from the
    same keyframe path an observer join takes."""

    async def test_not_authenticated_sends_error(self):
        conn = FakeConnection()

        await handlers.handle_resync(conn, Envelope(type=MessageType.RESYNC))

        assert conn.errors == [ERROR_NOT_AUTHENTICATED]

    async def test_not_in_a_game_sends_error(self):
        conn = FakeConnection()
        PlayerSession("p1", conn)

        await handlers.handle_resync(conn, Envelope(type=MessageType.RESYNC))

        assert conn.errors == [ERROR_NOT_IN_GAME]

    async def test_a_player_gets_a_personal_keyframe(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        game = _create_test_game(PlayerSession("p1", conn_a), PlayerSession("p2", conn_b))

        await handlers.handle_resync(conn_a, Envelope(type=MessageType.RESYNC))

        assert len(conn_a.sent) == 1
        keyframe = conn_a.sent[0]
        assert keyframe.type == MessageType.KEYFRAME
        assert keyframe.game_id == game.id
        assert len(keyframe.payload["pieces"]) == 32
        assert conn_b.sent == []  # personal, not a broadcast

    async def test_an_observer_gets_one_too(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        game = _create_test_game(PlayerSession("p1", conn_a), PlayerSession("p2", conn_b))
        conn_obs = FakeConnection()
        observer = PlayerSession("obs", conn_obs)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        await handlers.handle_resync(conn_obs, Envelope(type=MessageType.RESYNC))

        assert conn_obs.sent[0].type == MessageType.KEYFRAME


class TestHandleJump:
    async def test_not_authenticated_sends_error(self):
        conn = FakeConnection()
        envelope = Envelope(type=MessageType.JUMP, payload={"pos": {"x": 6, "y": 0}})

        await handlers.handle_jump(conn, envelope)

        assert conn.errors == [ERROR_NOT_AUTHENTICATED]

    async def test_not_in_a_game_sends_error(self):
        conn = FakeConnection()
        PlayerSession("p1", conn)
        envelope = Envelope(type=MessageType.JUMP, payload={"pos": {"x": 6, "y": 0}})

        await handlers.handle_jump(conn, envelope)

        assert conn.errors == [ERROR_NOT_IN_GAME]

    async def test_observer_cannot_jump(self):
        conn_a, conn_b, conn_obs = FakeConnection(), FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        game = _create_test_game(player_a, player_b)
        observer = PlayerSession("obs", conn_obs)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        # observer check happens before payload validation, so an empty
        # payload still proves the right rejection reason.
        envelope = Envelope(type=MessageType.JUMP, payload={})
        await handlers.handle_jump(conn_obs, envelope)

        assert conn_obs.errors == [ERROR_OBSERVER_CANNOT_MOVE]

    async def test_wrong_owner_jump_errors(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b)

        envelope = Envelope(type=MessageType.JUMP, payload={"pos": {"x": 1, "y": 0}})
        await handlers.handle_jump(conn_a, envelope)

        assert conn_a.errors == [ERROR_NOT_YOUR_PIECE]

    async def test_valid_jump_broadcasts_a_delta(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b)

        envelope = Envelope(type=MessageType.JUMP, payload={"pos": {"x": 6, "y": 0}})
        await handlers.handle_jump(conn_a, envelope)

        assert conn_a.errors == []
        assert any(e.type == MessageType.DELTA for e in conn_a.sent)
        assert any(e.type == MessageType.DELTA for e in conn_b.sent)


class TestOnGameFinalized:
    async def test_removes_game_and_frees_room_membership(self):
        handlers.persistence = _CannedPersistence()
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        result_a = handlers.room_manager.create_room(player_a)
        handlers.room_manager.join(result_a.room.name, player_b)

        game = handlers.registry.create_game(
            player_a,
            player_b,
            handlers.clock,
            handlers.persistence,
            room_id=result_a.room.name,
            on_finalize=handlers._on_game_finalized,
        )
        handlers.room_manager.mark_live(result_a.room, game.id)

        await game.finalize_by_forfeit(Color.BLACK, GAME_OVER_REASON_DISCONNECT)

        assert handlers.registry.get(game.id) is None
        assert handlers.room_manager.room_of("p1") is None
        assert handlers.room_manager.room_of("p2") is None

    async def test_frees_observers_too_and_closes_the_room(self):
        """An observer must not be left wedged in room_manager once the
        game ends (§8.7), and once every participant -- players and
        observers -- has left, the room itself must close rather than
        keep dangling on a game_id the registry already dropped (§8.8)."""
        handlers.persistence = _CannedPersistence()
        conn_a, conn_b, conn_obs = FakeConnection(), FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        observer = PlayerSession("obs", conn_obs)
        result_a = handlers.room_manager.create_room(player_a)
        handlers.room_manager.join(result_a.room.name, player_b)
        room_id = result_a.room.name
        handlers.room_manager.join(room_id, observer)

        game = handlers.registry.create_game(
            player_a,
            player_b,
            handlers.clock,
            handlers.persistence,
            room_id=room_id,
            on_finalize=handlers._on_game_finalized,
        )
        handlers.room_manager.mark_live(result_a.room, game.id)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        await game.finalize_by_forfeit(Color.BLACK, GAME_OVER_REASON_DISCONNECT)

        assert handlers.room_manager.room_of("obs") is None
        assert handlers.room_manager.room_exists(room_id) is False


class TestHandleResign:
    async def test_not_authenticated_sends_error(self):
        conn = FakeConnection()
        await handlers.handle_resign(conn, Envelope(type=MessageType.RESIGN, payload={}))

        assert conn.errors == [ERROR_NOT_AUTHENTICATED]

    async def test_not_in_a_game_sends_error(self):
        conn = FakeConnection()
        PlayerSession("p1", conn)

        await handlers.handle_resign(conn, Envelope(type=MessageType.RESIGN, payload={}))

        assert conn.errors == [ERROR_NOT_IN_GAME]

    async def test_observer_cannot_resign(self):
        handlers.persistence = _CannedPersistence()
        conn_a, conn_b, conn_obs = FakeConnection(), FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        game = _create_test_game(player_a, player_b)
        observer = PlayerSession("obs", conn_obs)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        await handlers.handle_resign(conn_obs, Envelope(type=MessageType.RESIGN, payload={}))

        assert conn_obs.errors == [ERROR_OBSERVER_CANNOT_RESIGN]

    async def test_resigning_player_forfeits_to_opponent(self):
        handlers.persistence = _CannedPersistence()
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b)

        await handlers.handle_resign(conn_a, Envelope(type=MessageType.RESIGN, payload={}))

        for conn in (conn_a, conn_b):
            game_over = [e for e in conn.sent if e.type == MessageType.GAME_OVER]
            assert len(game_over) == 1
            assert game_over[0].payload["winner"] == Color.BLACK.value
            assert game_over[0].payload["reason"] == GAME_OVER_REASON_RESIGNATION
