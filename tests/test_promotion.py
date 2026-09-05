from model.board import Board
from model.piece import Piece, PieceType
from model.position import Position
from rules.promotion import is_promotion_square

EMPTY = None


def make_empty_board(rows=8, cols=8):
    return Board([[EMPTY] * cols for _ in range(rows)])


def test_white_pawn_on_last_row_should_promote():
    board = make_empty_board()
    pawn = Piece("wP", "w", "P", Position(0, 0))
    assert is_promotion_square(board, pawn)


def test_black_pawn_on_last_row_should_promote():
    board = make_empty_board()
    pawn = Piece("bP", "b", "P", Position(board.rows - 1, 0))
    assert is_promotion_square(board, pawn)


def test_pawn_not_on_last_row_does_not_promote():
    board = make_empty_board()
    pawn = Piece("wP", "w", "P", Position(1, 0))
    assert not is_promotion_square(board, pawn)


def test_non_pawn_on_last_row_does_not_promote():
    board = make_empty_board()
    rook = Piece("wR", "w", "R", Position(0, 0))
    assert not is_promotion_square(board, rook)
