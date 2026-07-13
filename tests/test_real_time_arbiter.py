import pytest
from unittest.mock import MagicMock
from model.board import Board
from model.piece import Piece, PieceType, State, Color
from model.position import Position
from real_time.real_time_arbiter import RealTimeArbiter, DEFAULT_MOVE_DELAY_MS

EMPTY = "."


def empty_board(rows=8, cols=8):
    return Board([[EMPTY] * cols for _ in range(rows)])


KIND_MAP = {"PAWN": "P", "KNIGHT": "N", "BISHOP": "B", "ROOK": "R", "QUEEN": "Q", "KING": "K"}

def place(board, color, kind, x, y):
    c = color[0].lower()
    k = KIND_MAP[kind]
    p = Piece(f"{c}{k}", c, k, Position(x, y))
    board.set_piece_at(Position(x, y), p)
    return p


def pos(x, y):
    return Position(x, y)


class TestAddMove:
    def test_add_move_returns_true_and_sets_state(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        result = arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert result is True
        assert rook.state == State.moving

    def test_add_move_calculates_arrival_time(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert arb.pending_moves[0].arrival_time == 3 * DEFAULT_MOVE_DELAY_MS

    def test_add_move_diagonal_uses_max_distance(self):
        b = empty_board()
        bishop = place(b, "WHITE", "BISHOP", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(bishop, pos(0, 0), pos(3, 5))
        assert arb.pending_moves[0].arrival_time == 5 * DEFAULT_MOVE_DELAY_MS

    def test_duplicate_origin_rejected(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        result = arb.add_move(rook, pos(0, 0), pos(0, 5))
        assert result is False
        assert len(arb.pending_moves) == 1

    def test_different_origins_both_accepted(self):
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 0)
        rook2 = place(b, "WHITE", "ROOK", 1, 0)
        arb = RealTimeArbiter(b)
        assert arb.add_move(rook1, pos(0, 0), pos(0, 3)) is True
        assert arb.add_move(rook2, pos(1, 0), pos(1, 3)) is True
        assert len(arb.pending_moves) == 2


class TestAdvanceTime:
    def test_move_not_applied_before_arrival(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)  # only 1ms worth, needs 3
        assert b.get_piece_at(pos(0, 0)) == rook
        assert b.get_piece_at(pos(0, 3)) == EMPTY

    def test_move_applied_at_arrival(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == rook
        assert b.get_piece_at(pos(0, 0)) == EMPTY

    def test_piece_state_idle_after_arrival(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert rook.state == State.idle

    def test_move_removed_from_pending_after_arrival(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert len(arb.pending_moves) == 0

    def test_returns_false_when_no_king_captured(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS) is False

    def test_returns_true_when_king_captured(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "KING", 0, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS) is True

    def test_clock_accumulates_across_calls(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == rook


class TestCollision:
    def test_collision_clears_both_pieces(self):
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 3)
        rook2 = place(b, "BLACK", "ROOK", 6, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(rook1, pos(0, 3), pos(3, 3))
        arb.add_move(rook2, pos(6, 3), pos(3, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(3, 3)) == EMPTY

    def test_collision_clears_origins(self):
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 3)
        rook2 = place(b, "BLACK", "ROOK", 6, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(rook1, pos(0, 3), pos(3, 3))
        arb.add_move(rook2, pos(6, 3), pos(3, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == EMPTY
        assert b.get_piece_at(pos(6, 3)) == EMPTY


class TestIsStillValid:
    def test_move_invalidated_if_path_blocked(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 5))
        # block the path before arrival
        blocker = place(b, "WHITE", "PAWN", 0, 3)
        rook.state = State.moving  # keep state as moving
        arb.advance_time(5 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 5)) == EMPTY

    def test_move_invalidated_if_friendly_occupies_target(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        place(b, "WHITE", "PAWN", 0, 3)
        rook.state = State.moving
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 0)) == rook  # rook stays

    def test_move_invalidated_if_piece_captured(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        rook.state = State.captured  # piece was captured mid-flight
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == EMPTY

    def test_enemy_at_target_is_valid(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        enemy = place(b, "BLACK", "PAWN", 0, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == rook


class TestMultipleMoves:
    def test_two_independent_moves_both_applied(self):
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 0)
        rook2 = place(b, "BLACK", "ROOK", 7, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(rook1, pos(0, 0), pos(0, 3))
        arb.add_move(rook2, pos(7, 7), pos(7, 4))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == rook1
        assert b.get_piece_at(pos(7, 4)) == rook2

    def test_earlier_move_applied_first(self):
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 0)
        rook2 = place(b, "WHITE", "ROOK", 7, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook1, pos(0, 0), pos(0, 2))  # arrives at 2000ms
        arb.add_move(rook2, pos(7, 0), pos(7, 5))  # arrives at 5000ms
        arb.advance_time(2 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 2)) == rook1
        assert b.get_piece_at(pos(7, 0)) == rook2  # not yet arrived
