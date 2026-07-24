from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    AUTH = "auth"
    REGISTER = "register"
    LOGIN = "login"
    MOVE = "move"
    JUMP = "jump"
    STATE = "state"
    JOIN_ROOM = "join_room"
    GAME_START = "game_start"
    GAME_OVER = "game_over"
    RESIGN = "resign"
    CHAT = "chat"
    ERROR = "error"


class Envelope(BaseModel):
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    game_id: Optional[str] = None
