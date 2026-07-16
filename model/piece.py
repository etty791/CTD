
from enum import Enum    
class State(Enum):
    idle = "idle"
    moving = "moving"
    captured = "captured"
    airborne = "airborne"
    long_rest = "long_rest"
    short_rest = "short_rest"

    def is_resting(self) -> bool:
        return self in (State.long_rest, State.short_rest)
class PieceType(Enum):
    PAWN = "P"
    KNIGHT = "N"
    BISHOP = "B"
    ROOK = "R"
    QUEEN = "Q"
    KING = "K"
class Color(Enum):
    WHITE = "w"
    BLACK = "b"
class Piece:
    def __init__(self, id_num, color, type, position):
        self.id = id_num
        self.color = Color(color)
        self.type = PieceType(type)
        self.position = position
        self.state = State.idle
    def __str__(self):
        return f"{self.color.value}{self.type.value}"
