from model.piece import Piece, Color, PieceType, State
from model.position import Position
EMPTY_CELL= '.'

class Board:
    @classmethod
    def generate_standard_grid(cls):
        grid = [[EMPTY_CELL for _ in range(8)] for _ in range(8)]
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

        for col in range(8):
            place_piece(0, col, Color.BLACK, back_rank[col])
            place_piece(1, col, Color.BLACK, PieceType.PAWN)

        for col in range(8):
            place_piece(6, col, Color.WHITE, PieceType.PAWN)
            place_piece(7, col, Color.WHITE, back_rank[col])

        return grid
    
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
            self.get_piece_at(to_pos).state = State.captured
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
        if piece.type == PieceType.PAWN and piece.position.x == last_row:
            piece.type = PieceType.QUEEN

    