"""Routing and frame-sequencing tests for the client's ServerConnection.

Only the pure routing half is exercised: `_route` and `set_active_game` are
plain synchronous methods, so no websocket or network thread is involved.
`send` is stubbed out per test, since a RESYNC request is the one thing the
routing layer emits by itself.
"""

from client.network import ServerConnection
from shared.messages import DeltaPayload, GameOverPayload, KeyframePayload
from shared.protocol import Envelope, MessageType

SERVER_URL = "ws://test/ws"
FIRST_SEQ = 1


class FakeRemoteGame:
    def __init__(self):
        self.keyframes: list[KeyframePayload] = []
        self.deltas: list[DeltaPayload] = []
        self.ended: list[GameOverPayload] = []

    def apply_keyframe(self, payload: KeyframePayload) -> None:
        self.keyframes.append(payload)

    def apply_delta(self, payload: DeltaPayload) -> None:
        self.deltas.append(payload)

    def end_game(self, payload: GameOverPayload) -> None:
        self.ended.append(payload)


def keyframe_envelope(seq: int, server_time_ms: int = 0) -> Envelope:
    return Envelope(
        type=MessageType.KEYFRAME,
        seq=seq,
        payload=KeyframePayload(
            pieces=[], scores={"w": 0, "b": 0}, server_time_ms=server_time_ms
        ).model_dump(),
    )


def delta_envelope(seq: int, server_time_ms: int = 0) -> Envelope:
    return Envelope(
        type=MessageType.DELTA,
        seq=seq,
        payload=DeltaPayload(ops=[], server_time_ms=server_time_ms).model_dump(),
    )


def connected(game=None) -> tuple[ServerConnection, list[Envelope]]:
    """A ServerConnection with `send` captured instead of dialled."""
    connection = ServerConnection(SERVER_URL)
    sent: list[Envelope] = []
    connection.send = sent.append
    if game is not None:
        connection.set_active_game(game)
    return connection, sent


class TestFrameRouting:
    def test_a_keyframe_reaches_the_attached_game(self):
        game = FakeRemoteGame()
        connection, _ = connected(game)

        connection._route(keyframe_envelope(FIRST_SEQ, server_time_ms=100))

        assert [payload.server_time_ms for payload in game.keyframes] == [100]

    def test_a_delta_after_its_keyframe_is_applied(self):
        game = FakeRemoteGame()
        connection, _ = connected(game)

        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 1, server_time_ms=200))

        assert [payload.server_time_ms for payload in game.deltas] == [200]

    def test_frames_never_land_on_the_shell_inbox(self):
        connection, _ = connected()

        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 1))

        assert connection.inbox.empty()


class TestEarlyFrames:
    """The server sends GAME_START then a keyframe faster than the main
    thread can build the RemoteGame. Frames are published on change, so
    losing them could leave the player staring at an empty board."""

    def test_frames_that_beat_the_attachment_are_replayed_in_order(self):
        connection, _ = connected()

        connection._route(keyframe_envelope(FIRST_SEQ, server_time_ms=100))
        connection._route(delta_envelope(FIRST_SEQ + 1, server_time_ms=200))
        game = FakeRemoteGame()
        connection.set_active_game(game)

        assert [payload.server_time_ms for payload in game.keyframes] == [100]
        assert [payload.server_time_ms for payload in game.deltas] == [200]

    def test_replayed_frames_are_not_handed_to_the_next_game(self):
        connection, _ = connected()
        connection._route(keyframe_envelope(FIRST_SEQ))
        connection.set_active_game(FakeRemoteGame())
        connection.set_active_game(None)

        next_game = FakeRemoteGame()
        connection.set_active_game(next_game)

        assert next_game.keyframes == []

    def test_a_new_game_starts_its_sequence_from_scratch(self):
        connection, sent = connected()
        connection._route(keyframe_envelope(9))
        connection.set_active_game(FakeRemoteGame())
        connection.set_active_game(None)

        game = FakeRemoteGame()
        connection.set_active_game(game)
        connection._route(keyframe_envelope(FIRST_SEQ))

        assert len(game.keyframes) == 1
        assert sent == []


class TestSequenceGaps:
    def test_a_gap_requests_a_resync_instead_of_applying_the_delta(self):
        game = FakeRemoteGame()
        connection, sent = connected(game)
        connection._route(keyframe_envelope(FIRST_SEQ))

        connection._route(delta_envelope(FIRST_SEQ + 2))  # FIRST_SEQ+1 was lost

        assert game.deltas == []
        assert [envelope.type for envelope in sent] == [MessageType.RESYNC]

    def test_deltas_are_ignored_until_the_keyframe_lands(self):
        game = FakeRemoteGame()
        connection, sent = connected(game)
        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 2))

        connection._route(delta_envelope(FIRST_SEQ + 3))

        assert game.deltas == []
        assert len(sent) == 1  # one RESYNC, not one per dropped delta

    def test_the_keyframe_recovers_the_stream(self):
        game = FakeRemoteGame()
        connection, _ = connected(game)
        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 2))

        connection._route(keyframe_envelope(FIRST_SEQ + 3, server_time_ms=300))
        connection._route(delta_envelope(FIRST_SEQ + 4, server_time_ms=400))

        assert [payload.server_time_ms for payload in game.keyframes] == [0, 300]
        assert [payload.server_time_ms for payload in game.deltas] == [400]

    def test_a_delta_already_applied_is_ignored_without_a_resync(self):
        game = FakeRemoteGame()
        connection, sent = connected(game)
        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 1))

        connection._route(delta_envelope(FIRST_SEQ + 1))

        assert len(game.deltas) == 1
        assert sent == []

    def test_a_stale_keyframe_does_not_rewind_the_board(self):
        """A personal keyframe (an observer join, a RESYNC answer) can be
        overtaken by a broadcast delta; applying it late would undo it."""
        game = FakeRemoteGame()
        connection, _ = connected(game)
        connection._route(keyframe_envelope(FIRST_SEQ))
        connection._route(delta_envelope(FIRST_SEQ + 1))

        connection._route(keyframe_envelope(FIRST_SEQ, server_time_ms=999))

        assert [payload.server_time_ms for payload in game.keyframes] == [0]


class TestOtherRouting:
    def test_game_over_reaches_the_attached_game(self):
        game = FakeRemoteGame()
        connection, _ = connected(game)

        connection._route(
            Envelope(
                type=MessageType.GAME_OVER,
                payload=GameOverPayload(winner="w", reason="king_captured").model_dump(),
            )
        )

        assert len(game.ended) == 1
        assert connection.inbox.empty()

    def test_shell_traffic_goes_to_the_inbox(self):
        connection, _ = connected()
        envelope = Envelope(type=MessageType.LOGIN, payload={})

        connection._route(envelope)

        assert connection.inbox.get_nowait() is envelope
