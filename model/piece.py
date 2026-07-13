
from enum import Enum    
class State(Enum):
    idle = "idle"
    moving = "moving"
    captured = "captured"
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
    def __init__(self, id_num, color, kind, position):
        self.id = id_num
        self.color = Color(color)
        self.kind = PieceType(kind)
        self.position = position
        self.state = State.idle
    def __str__(self):
        return f"{self.color.value}{self.kind.value}"
