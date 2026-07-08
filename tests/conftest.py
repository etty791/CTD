import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from board import Board
from game import KungFuChessGame
from helpers import make_board


@pytest.fixture
def empty_grid():
    return [['.' for _ in range(8)] for _ in range(8)]


@pytest.fixture
def empty_board(empty_grid):
    return make_board(empty_grid)


@pytest.fixture
def empty_game(empty_board):
    return KungFuChessGame(empty_board)


@pytest.fixture
def board_with_pieces():
    grid = [['.' for _ in range(8)] for _ in range(8)]
    grid[0][0] = 'wR'
    grid[0][4] = 'wK'
    grid[7][4] = 'bK'
    grid[3][3] = 'wQ'
    grid[4][4] = 'bP'
    return make_board(grid)


@pytest.fixture
def game_with_pieces(board_with_pieces):
    return KungFuChessGame(board_with_pieces)
