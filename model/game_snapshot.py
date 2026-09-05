from dataclasses import dataclass
from typing import Optional
from model.position import Position
from model.piece import State, PieceType, Color

# DTO מייצג כלי בודד, כפי שהוא נראה כלפי חוץ (view/input)
@dataclass
class PieceDTO:
    id: int
    position: Position
    type: PieceType
    color: Color
    state: State
    origin: Position    # move/jump start cell; equals position when idle
    target: Position    # move/jump destination cell; equals position when idle
    progress: float     # 0.0-1.0 fraction through the current move/jump; 0.0 when idle
    # Absolute clock times (ms) bounding the current move/jump, None when the
    # piece has none. `progress` is that same motion sampled at one instant;
    # these let a consumer that renders faster than it receives snapshots -
    # i.e. the networked client - recompute progress for itself instead.
    move_start_ms: Optional[int] = None
    move_arrival_ms: Optional[int] = None
