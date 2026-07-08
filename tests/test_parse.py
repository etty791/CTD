import pytest
from unittest.mock import patch
from parse_clean import is_valid_board, parse_input

VALID = {'.', 'wK', 'wQ', 'wR', 'wB', 'wN', 'wP', 'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'}


# --- is_valid_board ---

def test_valid_board():
    board = [['.', 'wK'], ['.', 'bK']]
    assert is_valid_board(board, VALID) is True


def test_empty_board_invalid(capsys):
    assert is_valid_board([], VALID) is False


def test_row_width_mismatch(capsys):
    board = [['.', 'wK'], ['.']]
    assert is_valid_board(board, VALID) is False
    captured = capsys.readouterr()
    assert 'ROW_WIDTH_MISMATCH' in captured.out


def test_unknown_token(capsys):
    board = [['.', 'XX']]
    assert is_valid_board(board, VALID) is False
    captured = capsys.readouterr()
    assert 'UNKNOWN_TOKEN' in captured.out


# --- parse_input ---

SAMPLE_INPUT = """Board:
. wK . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . . . .
. . . . . bK . .
Commands:
click 0 0
wait 1000
print board
"""


def test_parse_input_returns_board_and_commands():
    with patch('sys.stdin.read', return_value=SAMPLE_INPUT):
        board, commands = parse_input(VALID)
    assert len(board) == 8
    assert board[0][1] == 'wK'
    assert commands == ['click 0 0', 'wait 1000', 'print board']


def test_parse_input_board_dimensions():
    with patch('sys.stdin.read', return_value=SAMPLE_INPUT):
        board, _ = parse_input(VALID)
    assert all(len(row) == 8 for row in board)
