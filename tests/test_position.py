from model.position import position


def test_equal_positions():
    assert position(2, 3) == position(2, 3)

def test_different_row():
    assert position(1, 3) != position(2, 3)

def test_different_col():
    assert position(2, 1) != position(2, 3)

def test_str():
    assert str(position(2, 3)) == "(2, 3)"
