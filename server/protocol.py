from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    AUTH = "auth"
    MOVE = "move"
    STATE = "state"
    JOIN_ROOM = "join_room"
    RESIGN = "resign"
    CHAT = "chat"
    ERROR = "error"


class Envelope(BaseModel):
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    game_id: Optional[str] = None
