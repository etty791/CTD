import asyncio
import uuid

from fastapi import WebSocket

from server.messages import ErrorPayload
from server.protocol import Envelope, MessageType


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
        async with self._send_lock:
            await self.websocket.send_text(envelope.model_dump_json())

    async def send_error(self, message: str) -> None:
        await self.send(Envelope(type=MessageType.ERROR, payload=ErrorPayload(message=message).model_dump()))
