import pytest
from model.piece import Piece, Color, PieceType, State
from model.position import Position


@pytest.fixture
def pawn():
    return Piece("w1", "w", "P", Position(6, 0))


def test_piece_color(pawn):
    assert pawn.color == Color.WHITE

def test_piece_type(pawn):
    assert pawn.type == PieceType.PAWN

def test_piece_initial_state(pawn):
    assert pawn.state == State.idle

def test_piece_position(pawn):
    assert pawn.position == Position(6, 0)

def test_piece_id(pawn):
    assert pawn.id == "w1"
