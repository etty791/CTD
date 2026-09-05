import asyncio
import uuid

from fastapi import WebSocket

from observability.metrics import histogram
from observability.metrics_config import BYTE_BUCKETS, GAME_FRAME_BYTES, LABEL_TYPE
from shared.messages import ErrorPayload
from shared.protocol import Envelope, MessageType

_game_frame_bytes = histogram(GAME_FRAME_BYTES, (LABEL_TYPE,), buckets=BYTE_BUCKETS)


class Connection:
    def __init__(self, websocket: WebSocket):
        self.id: str = str(uuid.uuid4())
        self.websocket = websocket
        self.player_session = None  # set once authenticated
        # Once games tick, a broadcast task and handler replies can both call
        # send() on the same websocket concurrently; the lock serializes them so
        # their frames don't interleave.
        self._send_lock = asyncio.Lock()

    async def send(self, envelope: Envelope) -> None:
        await self.send_raw(envelope.model_dump_json(), envelope.type)

    async def send_raw(self, body: str, message_type: MessageType) -> None:
        """Send an already-serialized envelope. A frame fanned out to several
        recipients is serialized once by the caller and sent through here,
        rather than re-encoded per socket."""
        async with self._send_lock:
            _game_frame_bytes.observe(len(body.encode()), type=message_type.value)
            await self.websocket.send_text(body)

    async def send_error(self, message: str) -> None:
        await self.send(Envelope(type=MessageType.ERROR, payload=ErrorPayload(message=message).model_dump()))
