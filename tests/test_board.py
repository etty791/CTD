import pytest
from model.board import Board
from model.piece import Piece, Color, PieceType
from model.position import Position

EMPTY = '.'

def make_empty_board(rows=8, cols=8):
    return Board([[EMPTY] * cols for _ in range(rows)])

KIND_MAP = {"PAWN": "P", "KNIGHT": "N", "BISHOP": "B", "ROOK": "R", "QUEEN": "Q", "KING": "K"}

def make_piece(color="WHITE", kind="PAWN", x=0, y=0):
    c = color[0].lower()
    k = KIND_MAP[kind]
    return Piece(f"{c}{k}", c, k, Position(x, y))


def test_get_piece_at_empty():
    board = make_empty_board()
    assert board.get_piece_at(Position(0, 0)) == EMPTY

def test_set_and_get_piece():
    board = make_empty_board()
    piece = make_piece(x=3, y=3)
    board.set_piece_at(Position(3, 3), piece)
    assert board.get_piece_at(Position(3, 3)) is piece

def test_is_cell_empty():
    board = make_empty_board()
    assert board.is_cell_empty(Position(0, 0))
    board.set_piece_at(Position(0, 0), make_piece())
    assert not board.is_cell_empty(Position(0, 0))

def test_is_within_boundaries():
    board = make_empty_board()
    assert board.is_within_boundaries(Position(0, 0))
    assert board.is_within_boundaries(Position(7, 7))
    assert not board.is_within_boundaries(Position(8, 0))
    assert not board.is_within_boundaries(Position(0, 8))

def test_move_piece():
    board = make_empty_board()
    piece = make_piece(x=1, y=0)
    board.set_piece_at(Position(1, 0), piece)
    board.move_piece(Position(1, 0), Position(3, 0))
    assert board.get_piece_at(Position(3, 0)) is piece
    assert board.is_cell_empty(Position(1, 0))
    assert piece.position == Position(3, 0)

def test_move_piece_captures_enemy():
    board = make_empty_board()
    attacker = make_piece("WHITE", "ROOK", 0, 0)
    defender = make_piece("BLACK", "PAWN", 0, 5)
    board.set_piece_at(Position(0, 0), attacker)
    board.set_piece_at(Position(0, 5), defender)
    board.move_piece(Position(0, 0), Position(0, 5))
    assert defender.state == "captured"
    assert board.get_piece_at(Position(0, 5)) is attacker

def test_is_friendly():
    board = make_empty_board()
    piece = make_piece("WHITE", "PAWN", 2, 2)
    board.set_piece_at(Position(2, 2), piece)
    assert board.is_friendly(Position(2, 2), Color.WHITE)
    assert not board.is_friendly(Position(2, 2), Color.BLACK)

def test_is_enemy():
    board = make_empty_board()
    piece = make_piece("BLACK", "PAWN", 2, 2)
    board.set_piece_at(Position(2, 2), piece)
    assert board.is_enemy(Position(2, 2), Color.WHITE)
    assert not board.is_enemy(Position(2, 2), Color.BLACK)
