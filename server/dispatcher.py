from typing import Awaitable, Callable

from server.connection import Connection
from server.protocol import Envelope, MessageType
from server.server_config import ERROR_NO_HANDLER

Handler = Callable[[Connection, Envelope], Awaitable[None]]
_handlers: dict[MessageType, Handler] = {}


def register(msg_type: MessageType):
    def decorator(fn: Handler):
        _handlers[msg_type] = fn
        return fn
    return decorator


async def dispatch(conn: Connection, envelope: Envelope) -> None:
    handler = _handlers.get(envelope.type)
    if handler is None:
        await conn.send_error(ERROR_NO_HANDLER.format(type=envelope.type))
        return
    await handler(conn, envelope)
