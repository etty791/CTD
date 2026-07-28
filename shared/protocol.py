"""The envelope every WebSocket frame is wrapped in, and its message types."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    REGISTER = "register"
    LOGIN = "login"
    MOVE = "move"
    JUMP = "jump"
    STATE = "state"
    CREATE_ROOM = "create_room"
    JOIN_ROOM = "join_room"
    PLAY = "play"
    GAME_START = "game_start"
    GAME_OVER = "game_over"
    RESIGN = "resign"
    CANCEL_SEEK = "cancel_seek"
    EVENT = "event"
    ERROR = "error"


class Envelope(BaseModel):
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    game_id: Optional[str] = None
