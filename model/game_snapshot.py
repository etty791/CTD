from dataclasses import dataclass, asdict
from typing import List
from model.position import Position
from model.piece import State,PieceType, Color

# 1. הגדרת ה-DTO המייצג כלי בודד
@dataclass
class PieceDTO:
    position: Position
    type: PieceType    # או סוג ה-Enum המתאים (למשל PieceType)
    color: Color    # או סוג ה-Enum המתאים (למשל Color)
    state: State

class GameSnapshot:
    def __init__(self, board):
        self._board = board
        # self.turn = turn
        # self.move_history = move_history

    def get_all_pieces(self) -> List[PieceDTO]:
        pieces = []
        for row in range(self._board.rows):
            for col in range(self._board.cols):
                pos = Position(row, col)
                if not self._board.is_cell_empty(pos):
                    piece = self._board.get_piece_at(pos)
                    if piece.state != State.captured:
                        piece_dto = PieceDTO(
                            position=pos,
                            type=piece.type,
                            color=piece.color,
                            state=piece.state
                        )
                        pieces.append(piece_dto)
                        
        return pieces
