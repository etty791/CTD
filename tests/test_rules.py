import pytest
from rules import (
    validate_king_move,
    validate_rook_move,
    validate_bishop_move,
    validate_queen_move,
    validate_knight_move,
    compute_diff,
)
from helpers import make_board
from game import KungFuChessGame


@pytest.fixture
def clear_game():
    grid = [['.' for _ in range(8)] for _ in range(8)]
    return KungFuChessGame(make_board(grid))


# --- compute_diff ---

def test_compute_diff_same_cell():
    assert compute_diff((3, 3), (3, 3)) == (0, 0)


def test_compute_diff_diagonal():
    assert compute_diff((0, 0), (3, 3)) == (3, 3)


# --- King ---

def test_king_valid_moves(clear_game):
    for origin, target in [((4, 4), (3, 3)), ((4, 4), (4, 5)), ((4, 4), (5, 4))]:
        assert validate_king_move(origin, target, 'w', clear_game) is True


def test_king_invalid_move(clear_game):
    assert validate_king_move((4, 4), (4, 6), 'w', clear_game) is False


# --- Rook ---

def test_rook_valid_horizontal(clear_game):
    assert validate_rook_move((4, 0), (4, 7), 'w', clear_game) is True


def test_rook_valid_vertical(clear_game):
    assert validate_rook_move((0, 4), (7, 4), 'w', clear_game) is True


def test_rook_invalid_diagonal(clear_game):
    assert validate_rook_move((0, 0), (3, 3), 'w', clear_game) is False


def test_rook_blocked(clear_game):
    clear_game.board.set_piece_at((4, 3), 'bP')
    assert validate_rook_move((4, 0), (4, 7), 'w', clear_game) is False


# --- Bishop ---

def test_bishop_valid_diagonal(clear_game):
    assert validate_bishop_move((0, 0), (4, 4), 'w', clear_game) is True


def test_bishop_invalid_straight(clear_game):
    assert validate_bishop_move((0, 0), (0, 4), 'w', clear_game) is False


def test_bishop_blocked(clear_game):
    clear_game.board.set_piece_at((2, 2), 'bP')
    assert validate_bishop_move((0, 0), (4, 4), 'w', clear_game) is False


# --- Queen ---

def test_queen_valid_straight(clear_game):
    assert validate_queen_move((4, 0), (4, 7), 'w', clear_game) is True


def test_queen_valid_diagonal(clear_game):
    assert validate_queen_move((0, 0), (4, 4), 'w', clear_game) is True


def test_queen_invalid_move(clear_game):
    assert validate_queen_move((0, 0), (1, 3), 'w', clear_game) is False


# --- Knight ---

def test_knight_valid_moves(clear_game):
    for target in [(2, 1), (1, 2), (2, -1), (-1, 2)]:
        row, col = 0 + target[0], 0 + target[1]
        if 0 <= row < 8 and 0 <= col < 8:
            assert validate_knight_move((0, 0), (row, col), 'w', clear_game) is True


def test_knight_invalid_move(clear_game):
    assert validate_knight_move((0, 0), (0, 3), 'w', clear_game) is False
    assert validate_knight_move((0, 0), (3, 3), 'w', clear_game) is False
