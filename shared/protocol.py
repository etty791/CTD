"""The envelope every WebSocket frame is wrapped in, and its message types."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    REGISTER = "register"
    LOGIN = "login"
    MOVE = "move"
    JUMP = "jump"
    KEYFRAME = "keyframe"
    DELTA = "delta"
    RESYNC = "resync"
    CREATE_ROOM = "create_room"
    JOIN_ROOM = "join_room"
    PLAY = "play"
    GAME_START = "game_start"
    GAME_OVER = "game_over"
    RESIGN = "resign"
    CANCEL_SEEK = "cancel_seek"
    ERROR = "error"


class Envelope(BaseModel):
    """`seq` numbers the frames of one game's state stream (KEYFRAME/DELTA)
    and is None on everything else. It sits at envelope level rather than
    inside the payload deliberately: gap detection and, later, routing must
    be possible without parsing a payload."""

    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    game_id: Optional[str] = None
    seq: Optional[int] = None
