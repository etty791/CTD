from concurrent.futures import Future

import pytest

from model.piece import Color
from server import handlers
from server.game_registry import GameRegistry
from server.main import _handle_disconnect
from server.persistence.user_repository import GameResultRatings
from server.rooms import RoomManager
from server.server_config import GAME_OVER_REASON_DISCONNECT
from server.session import PlayerSession
from shared.protocol import Envelope, MessageType


class FakeConnection:
    def __init__(self):
        self.player_session = None
        self.sent: list[Envelope] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    async def send_raw(self, body: str, message_type) -> None:
        await self.send(Envelope.model_validate_json(body))

    async def send_error(self, message: str) -> None:
        await self.send(Envelope(type=MessageType.ERROR, payload={"message": message}))


class _FakeHandle:
    def cancel(self) -> None:
        pass


class _FakeClock:
    def every(self, callback):
        return _FakeHandle()

    def after(self, delay_ms, callback):
        return _FakeHandle()

    def now_ms(self):
        return 0


class _InertPersistence:
    def submit(self, fn):
        future: Future = Future()
        future.set_result(None)
        return future


class _CannedPersistence:
    """Returns a preset GameResultRatings without running fn -- for tests
    whose game actually finalizes and needs finalize's Elo-consuming
    plumbing to work (real Elo math is covered by test_game_session.py)."""

    def __init__(self):
        self._ratings = GameResultRatings(
            white_old=1200, white_new=1216, black_old=1200, black_new=1184
        )

    def submit(self, fn):
        future: Future = Future()
        future.set_result(self._ratings)
        return future


def _create_test_game(player_a, player_b, persistence=None):
    return handlers.registry.create_game(
        player_a,
        player_b,
        handlers.clock,
        persistence or handlers.persistence,
        room_id="r1",
        on_finalize=handlers._on_game_finalized,
    )


@pytest.fixture(autouse=True)
def reset_handler_state():
    """handlers.* are module-level singletons; give each test a clean slate,
    matching the pattern in test_server_handlers.py."""
    handlers.registry = GameRegistry()
    handlers.room_manager = RoomManager()
    handlers.clock = _FakeClock()
    handlers.persistence = _InertPersistence()
    handlers.logged_in_usernames = set()
    yield
    handlers.registry = GameRegistry()
    handlers.room_manager = RoomManager()
    handlers.clock = _FakeClock()
    handlers.persistence = _InertPersistence()
    handlers.logged_in_usernames = set()


class TestHandleDisconnect:
    async def test_player_disconnect_still_forfeits_the_game(self):
        """Regression check on extracting _handle_disconnect out of
        websocket_endpoint: a disconnecting player must still forfeit to
        their opponent exactly as before."""
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)  # White
        player_b = PlayerSession("p2", conn_b)  # Black
        _create_test_game(player_a, player_b, persistence=_CannedPersistence())

        await _handle_disconnect(player_a)

        over = conn_b.sent[-1]
        assert over.type == MessageType.GAME_OVER
        assert over.payload["winner"] == Color.BLACK.value
        assert over.payload["reason"] == GAME_OVER_REASON_DISCONNECT
        assert "p1" not in handlers.logged_in_usernames

    async def test_observer_disconnect_leaves_the_room(self):
        """An observer whose socket drops mid-game (without ending it) must
        not stay wedged in room_manager -- the §8.9 fix."""
        conn_a, conn_b, conn_obs = FakeConnection(), FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        observer = PlayerSession("obs", conn_obs)
        result = handlers.room_manager.create_room(player_a)
        handlers.room_manager.join(result.room.name, player_b)
        handlers.room_manager.join(result.room.name, observer)

        game = _create_test_game(player_a, player_b)
        game.add_observer(observer)
        handlers.registry.add_observer(game.id, observer.player_id)

        await _handle_disconnect(observer)

        assert handlers.room_manager.room_of("obs") is None
        # the game itself is untouched -- only the observer left
        assert handlers.registry.get_game_for_player("p1") is game
        assert observer not in game.observers

    async def test_seeker_disconnect_leaves_the_seek_pool(self):
        """A session that was only ever in a room/seek (no game yet) still
        goes through room_manager.leave via the fallback branch."""
        conn = FakeConnection()
        player = PlayerSession("p1", conn)
        handlers.room_manager.create_room(player)

        await _handle_disconnect(player)

        assert handlers.room_manager.room_of("p1") is None
