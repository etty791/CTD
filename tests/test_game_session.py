from server.game_session import GameSession
from server.protocol import Envelope, MessageType
from server.session import PlayerSession

PIECE_KEYS = {"id", "position", "type", "color", "state", "origin", "target", "progress"}


class FakeConnection:
    def __init__(self):
        self.player_session = None
        self.sent: list[Envelope] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)


class TestBroadcastState:
    async def test_sends_typed_state_payload_to_both_players(self):
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("p1", conn_a)
        player_b = PlayerSession("p2", conn_b)
        session = GameSession(player_a, player_b)

        await session.broadcast_state()

        for conn in (conn_a, conn_b):
            assert len(conn.sent) == 1
            envelope = conn.sent[0]
            assert envelope.type == MessageType.STATE
            assert envelope.game_id == session.id
            assert set(envelope.payload.keys()) == {"pieces", "scores"}
            assert envelope.payload["scores"] == {"w": 0, "b": 0}
            # standard starting board has 32 pieces
            assert len(envelope.payload["pieces"]) == 32
            for piece in envelope.payload["pieces"]:
                assert set(piece.keys()) == PIECE_KEYS
                assert set(piece["position"].keys()) == {"x", "y"}
