from model.board import Board
from model.piece import Piece
from model.position import Position
from rules.rules_engine import validate_move

EMPTY = "."


def empty_board(rows=8, cols=8):
    return Board([[EMPTY] * cols for _ in range(rows)])


type_MAP = {"PAWN": "P", "KNIGHT": "N", "BISHOP": "B", "ROOK": "R", "QUEEN": "Q", "KING": "K"}

def place(board, color, type, x, y):
    c = color[0].lower()
    k = type_MAP[type]
    p = Piece(f"{c}{k}", c, k, Position(x, y))
    board.set_piece_at(Position(x, y), p)
    return p


def pos(x, y):
    return Position(x, y)


class TestValidateMove:
    def test_valid_rook_move(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)
        assert validate_move(b, pos(0, 0), pos(0, 5)).is_valid

    def test_invalid_rook_move_diagonal(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)
        result = validate_move(b, pos(0, 0), pos(3, 3))
        assert not result.is_valid and result.reason == "illegal_piece_move"

    def test_rook_blocked_by_friendly(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)
        place(b, "WHITE", "PAWN", 0, 3)
        assert not validate_move(b, pos(0, 0), pos(0, 5)).is_valid

    def test_rook_captures_enemy(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        assert validate_move(b, pos(0, 0), pos(0, 3)).is_valid

    def test_valid_bishop_move(self):
        b = empty_board()
        place(b, "WHITE", "BISHOP", 0, 0)
        assert validate_move(b, pos(0, 0), pos(3, 3)).is_valid

    def test_invalid_bishop_move_straight(self):
        b = empty_board()
        place(b, "WHITE", "BISHOP", 0, 0)
        assert not validate_move(b, pos(0, 0), pos(0, 3)).is_valid

    def test_valid_queen_move_straight(self):
        b = empty_board()
        place(b, "WHITE", "QUEEN", 3, 3)
        assert validate_move(b, pos(3, 3), pos(3, 7)).is_valid

    def test_valid_queen_move_diagonal(self):
        b = empty_board()
        place(b, "WHITE", "QUEEN", 3, 3)
        assert validate_move(b, pos(3, 3), pos(6, 6)).is_valid

    def test_invalid_queen_move_blocked_by_friendly(self):
        b = empty_board()
        place(b, "WHITE", "QUEEN", 3, 3)
        place(b, "WHITE", "PAWN", 3, 5)
        assert not validate_move(b, pos(3, 3), pos(3, 7)).is_valid

    def test_valid_knight_move(self):
        b = empty_board()
        place(b, "WHITE", "KNIGHT", 3, 3)
        assert validate_move(b, pos(3, 3), pos(4, 5)).is_valid

    def test_invalid_knight_move(self):
        b = empty_board()
        place(b, "WHITE", "KNIGHT", 3, 3)
        assert not validate_move(b, pos(3, 3), pos(3, 5)).is_valid

    def test_valid_king_move(self):
        b = empty_board()
        place(b, "WHITE", "KING", 3, 3)
        assert validate_move(b, pos(3, 3), pos(3, 4)).is_valid

    def test_invalid_king_move_two_squares(self):
        b = empty_board()
        place(b, "WHITE", "KING", 3, 3)
        assert not validate_move(b, pos(3, 3), pos(3, 5)).is_valid

    def test_valid_pawn_single_step(self):
        b = empty_board()
        place(b, "WHITE", "PAWN", 4, 3)
        assert validate_move(b, pos(4, 3), pos(3, 3)).is_valid

    def test_invalid_pawn_move_backward(self):
        b = empty_board()
        place(b, "WHITE", "PAWN", 4, 3)
        assert not validate_move(b, pos(4, 3), pos(5, 3)).is_valid

    def test_valid_pawn_capture(self):
        b = empty_board()
        place(b, "WHITE", "PAWN", 4, 3)
        place(b, "BLACK", "PAWN", 3, 4)
        assert validate_move(b, pos(4, 3), pos(3, 4)).is_valid

    def test_invalid_pawn_forward_capture(self):
        b = empty_board()
        place(b, "WHITE", "PAWN", 4, 3)
        place(b, "BLACK", "PAWN", 3, 3)
        assert not validate_move(b, pos(4, 3), pos(3, 3)).is_valid
