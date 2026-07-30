import asyncio

from server.connection import Connection
from shared.protocol import Envelope, MessageType


class FakeWebSocket:
    """Records frames sent via send_text (the only method Connection.send uses)."""

    def __init__(self):
        self.frames: list[str] = []

    async def send_text(self, text: str) -> None:
        self.frames.append(text)


class TestConnectionSend:
    async def test_send_delivers_envelope(self):
        ws = FakeWebSocket()
        conn = Connection(ws)
        envelope = Envelope(type=MessageType.KEYFRAME, payload={"pieces": [], "scores": {}})

        await conn.send(envelope)

        assert len(ws.frames) == 1
        assert Envelope.model_validate_json(ws.frames[0]).type == MessageType.KEYFRAME

    async def test_send_error_goes_through_send(self):
        ws = FakeWebSocket()
        conn = Connection(ws)

        await conn.send_error("boom")

        assert len(ws.frames) == 1
        decoded = Envelope.model_validate_json(ws.frames[0])
        assert decoded.type == MessageType.ERROR
        assert decoded.payload["message"] == "boom"

    async def test_send_raw_delivers_a_pre_serialized_frame(self):
        ws = FakeWebSocket()
        conn = Connection(ws)
        body = Envelope(type=MessageType.DELTA, payload={"ops": []}).model_dump_json()

        await conn.send_raw(body, MessageType.DELTA)

        assert ws.frames == [body]

    def test_connection_exposes_a_send_lock(self):
        conn = Connection(FakeWebSocket())
        assert isinstance(conn._send_lock, asyncio.Lock)

    async def test_serialized_sends_all_delivered(self):
        ws = FakeWebSocket()
        conn = Connection(ws)
        envelopes = [
            Envelope(type=MessageType.KEYFRAME, payload={"pieces": [], "scores": {}})
            for _ in range(5)
        ]

        await asyncio.gather(*(conn.send(e) for e in envelopes))

        assert len(ws.frames) == 5
