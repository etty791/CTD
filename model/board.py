from model.piece import Piece, Color, PieceType
from model.position import Position
EMPTY_CELL= '.'

class Board:
    def __init__(self, initial_grid):
        self._grid = initial_grid
        self.rows = len(initial_grid)
        self.cols = len(initial_grid[0]) if self.rows > 0 else 0


    def get_piece_at(self, position):
        return self._grid[position.x][position.y]

    def set_piece_at(self, position, piece):
        self._grid[position.x][position.y] = piece  
        if piece != EMPTY_CELL:
            piece.position = position     
    def is_cell_empty(self, coordinates):
        return self.get_piece_at(coordinates) == EMPTY_CELL

    def is_within_boundaries(self, position):
        return 0 <=  position.x< self.rows and 0 <= position.y < self.cols
    
    def move_piece(self, from_pos, to_pos):
        piece = self.get_piece_at(from_pos)
        if self.get_piece_at(to_pos) != EMPTY_CELL:
            self.get_piece_at(to_pos).state = "captured" 
        self.set_piece_at(to_pos, piece)
        self.set_piece_at(from_pos, EMPTY_CELL)
        piece.position = to_pos
        self._apply_promotion(piece)

    def is_friendly(self, pos: Position, color: Color) -> bool:
        piece = self.get_piece_at(pos)
        return piece != EMPTY_CELL and piece.color == color

    def is_enemy(self, pos: Position, color: Color) -> bool:
        piece = self.get_piece_at(pos)
        return piece != EMPTY_CELL and piece.color != color

    def _apply_promotion(self, piece: Piece) -> None:
        last_row = 0 if piece.color == Color.WHITE else self.rows - 1
        if piece.kind == PieceType.PAWN and piece.position.x == last_row:
            piece.kind = PieceType.QUEEN