import pytest
from model.position import Position


def test_str():
    assert str(Position(1, 2)) == "(1, 2)"

def test_eq():
    assert Position(3, 4) == Position(3, 4)
    assert Position(1, 2) != Position(2, 1)

def test_add():
    result = Position(1, 2) + Position(3, 4)
    assert result == Position(4, 6)
