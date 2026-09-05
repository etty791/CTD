from model.board import Board
from model.piece import Color, Piece, PieceType


def is_promotion_square(board: Board, piece: Piece) -> bool:
    """Whether `piece` (assumed already placed at its current position) sits
    on the back rank it promotes on - the last row for White, the first for
    Black. Pure predicate: callers apply the resulting type change."""
    last_row = 0 if piece.color == Color.WHITE else board.rows - 1
    return piece.type == PieceType.PAWN and piece.position.x == last_row
