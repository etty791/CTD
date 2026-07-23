import pytest

from server import handlers
from server.protocol import Envelope, MessageType
from server.session import PlayerSession


class FakeConnection:
    def __init__(self):
        self.player_session = None
        self.sent: list[Envelope] = []
        self.errors: list[str] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    async def send_error(self, message: str) -> None:
        self.errors.append(message)
        await self.send(Envelope(type=MessageType.ERROR, payload={"message": message}))


@pytest.fixture(autouse=True)
def reset_handler_state():
    """handlers.registry / _waiting_player are module-level singletons; give
    each test a clean slate so games/waiting players don't leak across tests."""
    handlers.registry = handlers.registry.__class__()
    handlers._waiting_player = None
    yield
    handlers.registry = handlers.registry.__class__()
    handlers._waiting_player = None


class TestHandleAuth:
    async def test_missing_player_id_sends_validation_error(self):
        conn = FakeConnection()
        envelope = Envelope(type=MessageType.AUTH, payload={})

        await handlers.handle_auth(conn, envelope)

        assert conn.player_session is None
        assert len(conn.errors) == 1
        assert conn.sent[-1].type == MessageType.ERROR

    async def test_valid_payload_registers_player_session(self):
        conn = FakeConnection()
        envelope = Envelope(type=MessageType.AUTH, payload={"player_id": "p1"})

        await handlers.handle_auth(conn, envelope)

        assert conn.errors == []
        assert conn.player_session is not None
        assert conn.player_session.player_id == "p1"
        assert conn.sent[-1].type == MessageType.AUTH
        assert conn.sent[-1].payload == {"status": "ok", "player_id": "p1"}


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
        handlers.registry.create_game(player_a, player_b)
        envelope = Envelope(type=MessageType.MOVE, payload={"from": {"x": 0, "y": 0}})

        await handlers.handle_move(conn, envelope)

        assert len(conn.errors) == 1
        assert conn.sent[-1].type == MessageType.ERROR

    async def test_missing_from_key_sends_validation_error(self):
        conn = FakeConnection()
        player_a = PlayerSession("p1", conn)
        player_b = PlayerSession("p2", FakeConnection())
        handlers.registry.create_game(player_a, player_b)
        envelope = Envelope(type=MessageType.MOVE, payload={"to": {"x": 0, "y": 0}})

        await handlers.handle_move(conn, envelope)

        assert len(conn.errors) == 1
        assert conn.sent[-1].type == MessageType.ERROR
