from board import Board


def test_board_dimensions(empty_board):
    assert empty_board.rows == 8
    assert empty_board.cols == 8


def test_get_piece_at_empty(empty_board):
    assert empty_board.get_piece_at((0, 0)) == '.'


def test_set_and_get_piece(empty_board):
    empty_board.set_piece_at((3, 3), 'wQ')
    assert empty_board.get_piece_at((3, 3)) == 'wQ'


def test_is_cell_empty_true(empty_board):
    assert empty_board.is_cell_empty((0, 0)) is True


def test_is_cell_empty_false(empty_board):
    empty_board.set_piece_at((0, 0), 'bK')
    assert empty_board.is_cell_empty((0, 0)) is False


def test_is_within_boundaries_valid(empty_board):
    assert empty_board.is_within_boundaries((0, 0)) is True
    assert empty_board.is_within_boundaries((7, 7)) is True


def test_is_within_boundaries_invalid(empty_board):
    assert empty_board.is_within_boundaries((-1, 0)) is False
    assert empty_board.is_within_boundaries((8, 0)) is False
    assert empty_board.is_within_boundaries((0, 8)) is False


def test_board_empty_grid():
    b = Board([])
    assert b.rows == 0
    assert b.cols == 0
