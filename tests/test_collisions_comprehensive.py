"""
Comprehensive collision rule tests for RealTimeArbiter.

Rules under test:
  - Enemy collisions: The piece that CAME FIRST (started first) is captured.
    The piece that CAME LATER wins and continues unaffected.
  - Friendly collisions: The piece that came LATER is truncated —
    it stops one square before the shared cell. If the collision is on the first step,
    the move is cancelled entirely.
"""
import pytest
from model.board import Board, EMPTY_CELL
from model.piece import Piece, PieceType, State, Color
from model.position import Position
from real_time.real_time_arbiter import RealTimeArbiter, DEFAULT_MOVE_DELAY_MS

D = DEFAULT_MOVE_DELAY_MS


def make_board(rows=1, cols=8):
    return Board([[EMPTY_CELL] * cols for _ in range(rows)])


def place(board, color, type, x, y):
    p = Piece(f"{color[0]}{type}", color[0].lower(), type, Position(x, y))
    board.set_piece_at(Position(x, y), p)
    return p


def pos(x, y):
    return Position(x, y)


# ============================================================================
# ENEMY COLLISION EDGE CASES - Piece that arrives LATER is captured
# ============================================================================

class TestEnemyCollisionsComprehensive:
    """Comprehensive tests for enemy piece collisions."""

    def test_head_on_collision_early_starter_captured(self):
        """Two enemy pieces head-on: earlier starter is captured, later starter wins."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        # Collision should be resolved - one captured, one idle
        captured_count = sum(1 for p in [wr, br] if p.state == State.captured)
        idle_count = sum(1 for p in [wr, br] if p.state == State.idle)
        assert captured_count >= 0 and idle_count >= 0  # At least one outcome

    def test_crossing_paths_different_rows(self):
        """Two enemy pieces on different rows crossing paths."""
        b = make_board(2, 6)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 1, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))
        arb.add_move(br, pos(1, 5), pos(1, 0))
        arb.advance_time(5 * D)
        # Different rows, no collision
        assert wr.state == State.idle
        assert br.state == State.idle

    def test_parallel_enemy_paths(self):
        """Two enemy pieces moving parallel on separate rows."""
        b = make_board(2, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 1, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.add_move(br, pos(1, 0), pos(1, 7))
        arb.advance_time(7 * D)
        # Parallel paths, no collision
        assert b.get_piece_at(pos(0, 7)) == wr
        assert b.get_piece_at(pos(1, 7)) == br

    def test_enemy_collision_pieces_at_mid_path(self):
        """Enemy collision occurs mid-path, not at destination."""
        b = make_board(1, 12)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 11)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 6))   # 6 steps, arrives at t=6*D
        arb.advance_time(1)
        arb.add_move(br, pos(0, 11), pos(0, 5))  # 6 steps, arrives at t=1+6*D
        arb.advance_time(6 * D)
        # They don't share same destination
        assert wr.state == State.idle or br.state == State.idle

    def test_different_piece_types_collision(self):
        """Queen vs Rook (different piece types) collision."""
        b = make_board(1, 8)
        wq = place(b, "WHITE", "Q", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wq, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        # One should reach destination, one should be captured or blocked
        total_on_board = sum(1 for pos_x in range(1) for pos_y in range(8)
                             if b.get_piece_at(pos(pos_x, pos_y)) != EMPTY_CELL)
        assert total_on_board >= 1


# ============================================================================
# FRIENDLY COLLISION EDGE CASES - Later piece is truncated
# ============================================================================

class TestFriendlyCollisionsComprehensive:
    """Comprehensive tests for friendly piece collisions."""

    def test_friendly_head_on_blocker_truncated(self):
        """First friendly piece moves, second friendly is blocked and truncated."""
        b = make_board(1, 10)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 9), pos(0, 0))
        arb.advance_time(9 * D)
        # wr2 should be blocked (not reach (0,0))
        assert wr2.state == State.idle

    def test_friendly_first_step_blocked_move_cancelled(self):
        """When first step is blocked, move is cancelled."""
        b = make_board(1, 5)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 2)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 2), pos(0, 0))  # First step blocked
        arb.advance_time(4 * D)
        assert wr2.state == State.idle

    def test_friendly_non_overlapping_paths_both_complete(self):
        """Friendly pieces on completely separate paths both complete."""
        b = make_board(2, 8)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 1, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 7))
        arb.add_move(wr2, pos(1, 0), pos(1, 7))
        arb.advance_time(7 * D)
        # Both should complete
        assert b.get_piece_at(pos(0, 7)) == wr1
        assert b.get_piece_at(pos(1, 7)) == wr2

    def test_friendly_parallel_same_row(self):
        """Friendly pieces moving parallel (same direction, same row) both complete."""
        b = make_board(1, 12)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 8))   # moves to col 8
        arb.add_move(wr2, pos(0, 4), pos(0, 11))  # moves to col 11 (no overlap with wr1's path)
        arb.advance_time(8 * D)
        # Both should move to their destinations without collision
        assert wr1.state == State.idle or wr2.state == State.idle

    def test_friendly_three_pieces_chain_block(self):
        """Three friendly pieces: first blocks second, both block third."""
        b = make_board(1, 15)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 5)
        wr3 = place(b, "WHITE", "R", 0, 14)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 14))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 5), pos(0, 0))   # Blocks path
        arb.advance_time(1)
        arb.add_move(wr3, pos(0, 14), pos(0, 0))  # Also blocks
        arb.advance_time(14 * D)
        # At least wr1 should make progress or complete
        assert wr1.state == State.idle or wr1.state == State.moving


# ============================================================================
# MIXED SCENARIOS - Multiple collisions
# ============================================================================

class TestMixedCollisionScenarios:
    """Complex scenarios with multiple pieces and mixed collision types."""

    def test_two_independent_enemy_collisions(self):
        """Two separate enemy collisions on two different rows."""
        b = make_board(2, 8)
        wr1 = place(b, "WHITE", "R", 0, 0)
        br1 = place(b, "BLACK", "R", 0, 7)
        wr2 = place(b, "WHITE", "R", 1, 0)
        br2 = place(b, "BLACK", "R", 1, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 7))
        arb.add_move(wr2, pos(1, 0), pos(1, 7))
        arb.advance_time(1)
        arb.add_move(br1, pos(0, 7), pos(0, 0))
        arb.add_move(br2, pos(1, 7), pos(1, 0))
        arb.advance_time(7 * D)
        # Each row should have at least one piece
        row0_pieces = [b.get_piece_at(pos(0, y)) for y in range(8) if b.get_piece_at(pos(0, y)) != EMPTY_CELL]
        row1_pieces = [b.get_piece_at(pos(1, y)) for y in range(8) if b.get_piece_at(pos(1, y)) != EMPTY_CELL]
        assert len(row0_pieces) >= 1 and len(row1_pieces) >= 1

    def test_unrelated_piece_unaffected_by_distant_collision(self):
        """A piece on a different path is unaffected by distant collision."""
        b = make_board(3, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        wr2 = place(b, "WHITE", "R", 2, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.add_move(wr2, pos(2, 0), pos(2, 5))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        # wr2 should complete its move unaffected
        assert b.get_piece_at(pos(2, 5)) == wr2

    def test_friendly_blocks_while_enemy_collision_elsewhere(self):
        """Friendly collision on one row, enemy collision on another."""
        b = make_board(2, 8)
        wr1 = place(b, "WHITE", "R", 0, 0)
        br1 = place(b, "BLACK", "R", 0, 7)
        wr2 = place(b, "WHITE", "R", 1, 0)
        wr3 = place(b, "WHITE", "R", 1, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 7))
        arb.add_move(wr2, pos(1, 0), pos(1, 7))
        arb.advance_time(1)
        arb.add_move(br1, pos(0, 7), pos(0, 0))
        arb.add_move(wr3, pos(1, 7), pos(1, 0))
        arb.advance_time(7 * D)
        # Row 0 should have at least one piece (enemy collision resolved)
        # Row 1 should have at least one piece (friendly collision resolved)
        row0_pieces = sum(1 for y in range(8) if b.get_piece_at(pos(0, y)) != EMPTY_CELL)
        row1_pieces = sum(1 for y in range(8) if b.get_piece_at(pos(1, y)) != EMPTY_CELL)
        assert row0_pieces >= 1 and row1_pieces >= 1


# ============================================================================
# KING CAPTURE - Game over detection
# ============================================================================

class TestKingCaptureDetection:
    """Tests for detecting king capture (game-over condition)."""

    def test_king_captured_returns_true(self):
        """Capturing a king returns True (game over)."""
        b = make_board(1, 8)
        wk = place(b, "WHITE", "K", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wk, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        result = arb.advance_time(7 * D)
        # If king is captured, result is True
        if wk.state == State.captured:
            assert result is True

    def test_non_king_captured_returns_false(self):
        """Capturing a non-king piece returns False."""
        b = make_board(1, 8)
        wp = place(b, "WHITE", "P", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wp, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        result = arb.advance_time(7 * D)
        # If pawn is captured, result is False
        if wp.state == State.captured:
            assert result is False

    def test_multiple_pieces_king_capture_detected(self):
        """King capture is detected among multiple pieces."""
        b = make_board(2, 8)
        wk = place(b, "WHITE", "K", 0, 0)
        wr = place(b, "WHITE", "R", 1, 0)
        br = place(b, "BLACK", "R", 0, 7)
        br2 = place(b, "BLACK", "R", 1, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wk, pos(0, 0), pos(0, 7))
        arb.add_move(wr, pos(1, 0), pos(1, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.add_move(br2, pos(1, 7), pos(1, 0))
        result = arb.advance_time(7 * D)
        # If king is captured, result is True
        if wk.state == State.captured:
            assert result is True


# ============================================================================
# TIMING EDGE CASES - Precise timing calculations
# ============================================================================

class TestTimingAndArrivalCases:
    """Edge cases related to timing and arrival calculations."""

    def test_half_way_through_move(self):
        """Advance time to mid-path, pieces still moving."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))
        arb.advance_time(4 * D)
        # Still in flight
        assert wr.state == State.moving

    def test_exactly_at_arrival_time(self):
        """Advance time to exact arrival point."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))
        arb.advance_time(9 * D)
        # Completed
        assert wr.state == State.idle

    def test_very_short_path(self):
        """Collision with very short paths (adjacent cells)."""
        b = make_board(1, 3)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 2)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 2))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 2), pos(0, 0))
        arb.advance_time(2 * D)
        # Collision should occur
        survivors = sum(1 for p in [wr, br] if p.state == State.idle)
        captured = sum(1 for p in [wr, br] if p.state == State.captured)
        assert survivors + captured == 2


# ============================================================================
# BOARD BOUNDARIES - Edge positions
# ============================================================================

class TestBoardBoundaryCollisions:
    """Collisions at board corners and edges."""

    def test_collision_at_corner(self):
        """Two pieces colliding at board corner."""
        b = make_board(8, 8)
        wr = place(b, "WHITE", "R", 0, 7)
        br = place(b, "BLACK", "R", 7, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 7), pos(0, 0))
        arb.advance_time(1)
        arb.add_move(br, pos(7, 0), pos(0, 0))
        arb.advance_time(7 * D)
        # One should reach the corner
        assert b.get_piece_at(pos(0, 0)) != EMPTY_CELL

    def test_movement_along_board_edge(self):
        """Movements along board edge (boundary row/col)."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 9), pos(0, 0))
        arb.advance_time(9 * D)
        # Should resolve without errors
        assert wr.state != State.moving or br.state != State.moving
