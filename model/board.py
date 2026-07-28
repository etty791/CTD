from typing import Optional

from model.piece import Piece, Color, PieceType
from model.position import Position

BOARD_SIZE = 8

class Board:
    @classmethod
    def generate_standard_grid(cls):
        grid = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        piece_id = 1

        def place_piece(row, col, color, p_type):
            nonlocal piece_id
            grid[row][col] = Piece(
                id_num=piece_id,
                color=color.value,
                type=p_type.value,
                position=Position(row, col)
            )
            piece_id += 1

        back_rank = [
            PieceType.ROOK, PieceType.KNIGHT, PieceType.BISHOP, PieceType.QUEEN,
            PieceType.KING, PieceType.BISHOP, PieceType.KNIGHT, PieceType.ROOK
        ]

        for col in range(BOARD_SIZE):
            place_piece(0, col, Color.BLACK, back_rank[col])
            place_piece(1, col, Color.BLACK, PieceType.PAWN)

        for col in range(BOARD_SIZE):
            place_piece(6, col, Color.WHITE, PieceType.PAWN)
            place_piece(7, col, Color.WHITE, back_rank[col])

        return grid

    def __init__(self, initial_grid):
        self._grid = initial_grid
        self.rows = len(initial_grid)
        self.cols = len(initial_grid[0]) if self.rows > 0 else 0


    def get_piece_at(self, position: Position) -> Optional[Piece]:
        return self._grid[position.x][position.y]

    def set_piece_at(self, position: Position, piece: Optional[Piece]) -> None:
        self._grid[position.x][position.y] = piece
        if piece is not None:
            piece.position = position
    def is_cell_empty(self, coordinates):
        return self.get_piece_at(coordinates) is None

    def is_within_boundaries(self, position):
        return 0 <=  position.x< self.rows and 0 <= position.y < self.cols

    def move_piece(self, from_pos, to_pos):
        """Relocate the piece at `from_pos` to `to_pos`, overwriting
        whatever was there. Capture bookkeeping (marking a displaced
        occupant as State.captured) is not this method's job - it is the
        arbiter's, via RealTimeArbiter._mark_captured - so callers that
        care about a captured occupant must handle it themselves before
        calling this."""
        piece = self.get_piece_at(from_pos)
        self.set_piece_at(to_pos, piece)
        self.set_piece_at(from_pos, None)
        piece.position = to_pos

    def place_piece(self, position: Position, piece: Piece) -> None:
        """Set `position` to hold `piece`, syncing its .position. Promotion
        is a rule, not board state - callers that need it call
        rules.promotion.is_promotion_square themselves after placing."""
        self.set_piece_at(position, piece)

    def is_friendly(self, pos: Position, color: Color) -> bool:
        piece = self.get_piece_at(pos)
        return piece is not None and piece.color == color

    def is_enemy(self, pos: Position, color: Color) -> bool:
        piece = self.get_piece_at(pos)
        return piece is not None and piece.color != color
