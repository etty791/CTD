"""Routing tests for the client's ServerConnection.

Only the pure routing half is exercised: `_route` and `set_active_game` are
plain synchronous methods, so no websocket or network thread is involved.
"""

from client.network import ServerConnection
from shared.messages import GameOverPayload, StatePayload
from shared.protocol import Envelope, MessageType

SERVER_URL = "ws://test/ws"


class FakeRemoteGame:
    def __init__(self):
        self.applied: list[StatePayload] = []
        self.ended: list[GameOverPayload] = []

    def apply_state(self, payload: StatePayload) -> None:
        self.applied.append(payload)

    def end_game(self, payload: GameOverPayload) -> None:
        self.ended.append(payload)


def state_envelope(server_time_ms: int) -> Envelope:
    return Envelope(
        type=MessageType.STATE,
        payload=StatePayload(
            pieces=[], scores={"w": 0, "b": 0}, server_time_ms=server_time_ms
        ).model_dump(),
    )


class TestStateRouting:
    def test_state_reaches_the_attached_game(self):
        connection = ServerConnection(SERVER_URL)
        game = FakeRemoteGame()
        connection.set_active_game(game)

        connection._route(state_envelope(100))

        assert [payload.server_time_ms for payload in game.applied] == [100]

    def test_state_that_beat_the_attachment_is_replayed_on_attach(self):
        # The server sends GAME_START then STATE faster than the main thread
        # can build the RemoteGame. Frames are published on change, so losing
        # this one could leave the player staring at an empty board.
        connection = ServerConnection(SERVER_URL)

        connection._route(state_envelope(100))
        game = FakeRemoteGame()
        connection.set_active_game(game)

        assert [payload.server_time_ms for payload in game.applied] == [100]

    def test_only_the_newest_early_frame_is_replayed(self):
        connection = ServerConnection(SERVER_URL)

        connection._route(state_envelope(100))
        connection._route(state_envelope(200))
        game = FakeRemoteGame()
        connection.set_active_game(game)

        assert [payload.server_time_ms for payload in game.applied] == [200]

    def test_a_replayed_frame_is_not_handed_to_the_next_game(self):
        connection = ServerConnection(SERVER_URL)
        connection._route(state_envelope(100))
        connection.set_active_game(FakeRemoteGame())
        connection.set_active_game(None)

        next_game = FakeRemoteGame()
        connection.set_active_game(next_game)

        assert next_game.applied == []

    def test_state_never_lands_on_the_shell_inbox(self):
        connection = ServerConnection(SERVER_URL)

        connection._route(state_envelope(100))

        assert connection.inbox.empty()


class TestOtherRouting:
    def test_game_over_reaches_the_attached_game(self):
        connection = ServerConnection(SERVER_URL)
        game = FakeRemoteGame()
        connection.set_active_game(game)

        connection._route(
            Envelope(
                type=MessageType.GAME_OVER,
                payload=GameOverPayload(winner="w", reason="king_captured").model_dump(),
            )
        )

        assert len(game.ended) == 1
        assert connection.inbox.empty()

    def test_shell_traffic_goes_to_the_inbox(self):
        connection = ServerConnection(SERVER_URL)
        envelope = Envelope(type=MessageType.LOGIN, payload={})

        connection._route(envelope)

        assert connection.inbox.get_nowait() is envelope
