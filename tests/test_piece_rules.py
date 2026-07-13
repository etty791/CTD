import pytest
from model.board import Board
from model.piece import Piece
from model.position import Position
from rules.piece_rules import RookRules, BishopRules, QueenRules, KnightRules, KingRules, PawnRules

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


# ---------------------------------------------------------------------------
# Rook
# ---------------------------------------------------------------------------

class TestRookRules:
    R = RookRules()

    def test_open_board_14_squares(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 3, 3)
        assert len(self.R.legal_destinations(b, rook)) == 14

    def test_friendly_blocks_and_is_excluded(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "WHITE", "PAWN", 0, 3)
        dests = self.R.legal_destinations(b, rook)
        assert pos(0, 3) not in dests
        assert pos(0, 4) not in dests

    def test_enemy_is_capturable_but_does_not_pass_through(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        dests = self.R.legal_destinations(b, rook)
        assert pos(0, 3) in dests
        assert pos(0, 4) not in dests

    def test_fully_surrounded_by_friendlies_no_moves(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 3, 3)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            place(b, "WHITE", "PAWN", 3 + dx, 3 + dy)
        assert len(self.R.legal_destinations(b, rook)) == 0

    def test_fully_surrounded_by_enemies_can_capture_all_four(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 3, 3)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            place(b, "BLACK", "PAWN", 3 + dx, 3 + dy)
        dests = self.R.legal_destinations(b, rook)
        assert dests == {pos(4, 3), pos(2, 3), pos(3, 4), pos(3, 2)}


# ---------------------------------------------------------------------------
# Bishop
# ---------------------------------------------------------------------------

class TestBishopRules:
    B = BishopRules()

    def test_open_board_center_13_squares(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 3, 3)
        assert len(self.B.legal_destinations(b, bishop)) == 13

    def test_corner_has_7_squares(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 0, 0)
        assert len(self.B.legal_destinations(b, bishop)) == 7

    def test_friendly_blocks_diagonal(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 0, 0)
        place(b, "WHITE", "PAWN", 2, 2)
        dests = self.B.legal_destinations(b, bishop)
        assert pos(2, 2) not in dests
        assert pos(3, 3) not in dests

    def test_enemy_capturable_stops_slide(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 0, 0)
        place(b, "BLACK", "PAWN", 2, 2)
        dests = self.B.legal_destinations(b, bishop)
        assert pos(2, 2) in dests
        assert pos(3, 3) not in dests

    def test_fully_surrounded_by_enemies_can_capture_all_four(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 3, 3)
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            place(b, "BLACK", "PAWN", 3 + dx, 3 + dy)
        dests = self.B.legal_destinations(b, bishop)
        assert dests == {pos(4, 4), pos(4, 2), pos(2, 4), pos(2, 2)}


# ---------------------------------------------------------------------------
# Queen
# ---------------------------------------------------------------------------

class TestQueenRules:
    Q = QueenRules()

    def test_equals_rook_union_bishop(self):
        b = empty_board()
        queen = place(b, "WHITE", "QUEEN", 3, 3)
        expected = RookRules().legal_destinations(b, queen) | BishopRules().legal_destinations(b, queen)
        assert self.Q.legal_destinations(b, queen) == expected

    def test_blocked_by_friendlies_no_moves(self):
        b = empty_board()
        queen = place(b, "WHITE", "QUEEN", 3, 3)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                place(b, "WHITE", "PAWN", 3 + dx, 3 + dy)
        assert len(self.Q.legal_destinations(b, queen)) == 0

    def test_surrounded_by_enemies_can_capture_all_eight(self):
        b = empty_board()
        queen = place(b, "WHITE", "QUEEN", 3, 3)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                place(b, "BLACK", "PAWN", 3 + dx, 3 + dy)
        assert len(self.Q.legal_destinations(b, queen)) == 8


# ---------------------------------------------------------------------------
# Knight
# ---------------------------------------------------------------------------

class TestKnightRules:
    N = KnightRules()

    def test_center_has_8_moves(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 3, 3)
        assert len(self.N.legal_destinations(b, knight)) == 8

    def test_corner_has_2_moves(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 0, 0)
        assert self.N.legal_destinations(b, knight) == {pos(1, 2), pos(2, 1)}

    def test_friendly_square_excluded(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 3, 3)
        place(b, "WHITE", "PAWN", 4, 5)
        assert pos(4, 5) not in self.N.legal_destinations(b, knight)

    def test_enemy_square_included(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 3, 3)
        place(b, "BLACK", "PAWN", 4, 5)
        assert pos(4, 5) in self.N.legal_destinations(b, knight)

    def test_jumps_over_pieces(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 3, 3)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                place(b, "BLACK", "PAWN", 3 + dx, 3 + dy)
        assert len(self.N.legal_destinations(b, knight)) == 8


# ---------------------------------------------------------------------------
# King
# ---------------------------------------------------------------------------

class TestKingRules:
    K = KingRules()

    def test_center_has_8_moves(self):
        b = empty_board()
        king = place(b, "WHITE", "KING", 3, 3)
        assert len(self.K.legal_destinations(b, king)) == 8

    def test_corner_has_3_moves(self):
        b = empty_board()
        king = place(b, "WHITE", "KING", 0, 0)
        assert len(self.K.legal_destinations(b, king)) == 3

    def test_edge_has_5_moves(self):
        b = empty_board()
        king = place(b, "WHITE", "KING", 0, 3)
        assert len(self.K.legal_destinations(b, king)) == 5

    def test_friendly_excluded(self):
        b = empty_board()
        king = place(b, "WHITE", "KING", 3, 3)
        place(b, "WHITE", "PAWN", 3, 4)
        assert pos(3, 4) not in self.K.legal_destinations(b, king)

    def test_enemy_included(self):
        b = empty_board()
        king = place(b, "WHITE", "KING", 3, 3)
        place(b, "BLACK", "PAWN", 3, 4)
        assert pos(3, 4) in self.K.legal_destinations(b, king)


# ---------------------------------------------------------------------------
# Pawn
# ---------------------------------------------------------------------------

class TestPawnRules:
    P = PawnRules()

    def test_white_single_step(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 4, 3)
        assert pos(3, 3) in self.P.legal_destinations(b, pawn)

    def test_white_two_step_from_start_row(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 6, 3)
        assert pos(4, 3) in self.P.legal_destinations(b, pawn)

    def test_white_no_two_step_from_non_start_row(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 5, 3)
        assert pos(3, 3) not in self.P.legal_destinations(b, pawn)

    def test_white_blocked_forward(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 4, 3)
        place(b, "BLACK", "PAWN", 3, 3)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(3, 3) not in dests
        assert pos(2, 3) not in dests

    def test_white_two_step_blocked_if_one_step_blocked(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 6, 3)
        place(b, "BLACK", "PAWN", 5, 3)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(5, 3) not in dests
        assert pos(4, 3) not in dests

    def test_white_diagonal_capture(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 4, 3)
        place(b, "BLACK", "PAWN", 3, 2)
        place(b, "BLACK", "PAWN", 3, 4)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(3, 2) in dests
        assert pos(3, 4) in dests

    def test_white_no_capture_on_empty_diagonal(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 4, 3)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(3, 2) not in dests
        assert pos(3, 4) not in dests

    def test_white_cannot_capture_friendly_diagonally(self):
        b = empty_board()
        pawn = place(b, "WHITE", "PAWN", 4, 3)
        place(b, "WHITE", "PAWN", 3, 2)
        assert pos(3, 2) not in self.P.legal_destinations(b, pawn)

    def test_black_single_step(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 3, 3)
        assert pos(4, 3) in self.P.legal_destinations(b, pawn)

    def test_black_two_step_from_start_row(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 1, 3)
        assert pos(3, 3) in self.P.legal_destinations(b, pawn)

    def test_black_no_two_step_from_non_start_row(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 2, 3)
        assert pos(4, 3) not in self.P.legal_destinations(b, pawn)

    def test_black_blocked_forward(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 3, 3)
        place(b, "WHITE", "PAWN", 4, 3)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(4, 3) not in dests
        assert pos(5, 3) not in dests

    def test_black_diagonal_capture(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 3, 3)
        place(b, "WHITE", "PAWN", 4, 2)
        place(b, "WHITE", "PAWN", 4, 4)
        dests = self.P.legal_destinations(b, pawn)
        assert pos(4, 2) in dests
        assert pos(4, 4) in dests

    def test_black_cannot_capture_friendly_diagonally(self):
        b = empty_board()
        pawn = place(b, "BLACK", "PAWN", 3, 3)
        place(b, "BLACK", "PAWN", 4, 2)
        assert pos(4, 2) not in self.P.legal_destinations(b, pawn)
