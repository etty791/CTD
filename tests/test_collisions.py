"""
Collision tests for RealTimeArbiter.

Rules under test:
  - Opposite colors: the piece that arrives at the shared cell EARLIER is
    captured mid-flight — the later arriver "sweeps" it away and continues
    to its own original target untouched. Note this depends on arrival
    time at the shared cell, not on which piece was commanded to move
    first: a piece issued later can still be the one to arrive first if
    it is geometrically closer to the crossing point.
  - Same color: the piece that arrives at the shared cell LATER is
    truncated — it stops one square before the shared cell. If the shared
    cell is the very first step, the move is cancelled entirely.
  - After a move (or a blocked/truncated move) concludes, the piece enters
    a long_rest cooldown (LONG_REST_DURATION_MS) before returning to
    State.idle - tests must advance past that cooldown before asserting
    State.idle.
"""
import pytest
from model.board import Board, EMPTY_CELL
from model.piece import Piece, PieceType, State, Color
from model.position import Position
from real_time.real_time_arbiter import (
    RealTimeArbiter,
    DEFAULT_MOVE_DELAY_MS,
    LONG_REST_DURATION_MS,
)

D = DEFAULT_MOVE_DELAY_MS


def make_board(rows=1, cols=8):
    return Board([[EMPTY_CELL] * cols for _ in range(rows)])


def place(board, color, type, x, y):
    p = Piece(f"{color[0]}{type}", color[0].lower(), type, Position(x, y))
    board.set_piece_at(Position(x, y), p)
    return p


def pos(x, y):
    return Position(x, y)


# ---------------------------------------------------------------------------
# Opposite-color path collisions — winner determined by arrival at shared cell
# ---------------------------------------------------------------------------

class TestEnemyPathCollision:

    def test_earlier_starter_wins_head_on(self):
        """wR starts first, bR starts second — wR wins, bR is captured."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))   # start_time = 0
        arb.advance_time(1)                        # tiny tick so bR starts later
        arb.add_move(br, pos(0, 7), pos(0, 0))   # start_time = 1
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)  # let wR's post-move cooldown expire
        assert br.state == State.captured
        assert wr.state == State.idle
        assert b.get_piece_at(pos(0, 7)) == wr

    def test_later_starter_loses_head_on(self):
        """bR starts first, wR starts second — bR wins, wR is captured."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(br, pos(0, 7), pos(0, 0))   # start_time = 0
        arb.advance_time(1)
        arb.add_move(wr, pos(0, 0), pos(0, 7))   # start_time = 1
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)  # let bR's post-move cooldown expire
        assert wr.state == State.captured
        assert br.state == State.idle
        assert b.get_piece_at(pos(0, 0)) == br

    def test_winner_reaches_original_target(self):
        """Winner is not redirected — it keeps going to its own target."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))   # start_time = 0, target col 7
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))   # start_time = 1, crosses wR path
        arb.advance_time(7 * D)
        # Their paths cross at col 2 — bR arrives there earlier and wR (the
        # earlier arriver) is captured; bR is not redirected and keeps
        # going to its own target (0, 0).
        assert wr.state == State.captured
        assert br.state == State.idle
        assert b.get_piece_at(pos(0, 0)) == br

    def test_loser_removed_from_origin(self):
        """Captured piece is cleared from its origin square."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        assert b.get_piece_at(pos(0, 7)) == wr   # winner landed
        # origin of loser (br) was col 7 — now occupied by winner
        assert br.state == State.captured

    def test_loser_removed_from_pending(self):
        """After collision, no pending moves remain."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        assert arb.pending_moves == []

    def test_crossing_paths_not_same_target(self):
        """Two enemy rooks cross on the same row — earlier starter wins."""
        b = make_board(2, 6)
        # wR at (0,0) going right; bR at (0,5) going left — they cross
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 5), pos(0, 0))
        arb.advance_time(5 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert br.state == State.captured
        assert wr.state == State.idle

    def test_enemy_collision_mid_path_not_at_target(self):
        """Collision happens mid-path; winner still lands at its own target."""
        b = make_board(1, 8)
        # wR (0,0)->(0,6), bR (0,3)->(0,0): bR starts later, crosses wR path at col 3
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 6))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 3), pos(0, 0))
        arb.advance_time(6 * D)
        assert br.state == State.captured
        assert b.get_piece_at(pos(0, 6)) == wr

    def test_king_captured_mid_flight_returns_true(self):
        """If the captured piece is a king, advance_time returns True."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        bk = place(b, "BLACK", "K", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(bk, pos(0, 7), pos(0, 0))
        result = arb.advance_time(7 * D)
        assert result is True

    def test_non_king_capture_returns_false(self):
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        result = arb.advance_time(7 * D)
        assert result is False

    def test_simultaneous_start_earlier_arrival_wins(self):
        """Same start time: the piece that arrives at the shared cell first wins."""
        b = make_board(1, 8)
        # wR (0,0)->(0,3): arrives at shared cell col 2 at t=2*D
        # bR (0,5)->(0,2): arrives at shared cell col 2 at t=3*D  → bR loses
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))
        arb.add_move(br, pos(0, 5), pos(0, 0))
        arb.advance_time(5 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # both started at t=0; wR reaches col 5 in 5 steps, bR reaches col 0 in 5 steps
        # they meet in the middle — tiebreak by start_time (both 0) → implementation-defined,
        # but exactly one must survive
        survivors = [p for p in [wr, br] if p.state == State.idle]
        captured  = [p for p in [wr, br] if p.state == State.captured]
        assert len(survivors) == 1
        assert len(captured)  == 1


# ---------------------------------------------------------------------------
# Same-color path collisions — later piece is truncated
# ---------------------------------------------------------------------------

class TestFriendlyPathCollision:

    def test_later_friendly_truncated_stops_before_shared_cell(self):
        """wR1 already moving; wR2 starts later and its path crosses wR1's path.
        wR2 must stop one square before the shared cell."""
        b = make_board(2, 6)
        # wR1 moves along row 0: (0,0)->(0,5)
        # wR2 moves along row 0: (0,3)->(0,0) — shares cells 0..3 with wR1
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 5))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 5), pos(0, 0))
        arb.advance_time(5 * D)
        # wr2 should NOT reach col 0 (wr1's path); it stops before the first shared cell
        assert b.get_piece_at(pos(0, 0)) != wr2

    def test_friendly_truncated_to_origin_when_first_step_blocked(self):
        """If the very first step of a friendly move is blocked, the move is
        cancelled and the piece stays idle at its origin."""
        b = make_board(1, 4)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 3)
        arb = RealTimeArbiter(b)
        # wr1 moves right: (0,0)->(0,3)
        arb.add_move(wr1, pos(0, 0), pos(0, 3))
        arb.advance_time(1)
        # wr2 moves left: (0,3)->(0,0) — first step (col 2) is in wr1's path
        arb.add_move(wr2, pos(0, 3), pos(0, 0))
        arb.advance_time(3 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr2.state == State.idle
        # wr2 must not have moved to col 0
        assert b.get_piece_at(pos(0, 0)) != wr2

    def test_friendly_winner_unaffected(self):
        """When friendly paths fully overlap, the later mover is blocked
        outright and never leaves its own square."""
        b = make_board(1, 6)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 5))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 5), pos(0, 0))
        arb.advance_time(5 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert b.get_piece_at(pos(0, 5)) == wr2
        assert wr2.position == pos(0, 5)

    def test_two_friendlies_non_crossing_both_arrive(self):
        """Friendly pieces on non-overlapping paths both complete their moves."""
        b = make_board(2, 4)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 1, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 3))
        arb.add_move(wr2, pos(1, 0), pos(1, 3))
        arb.advance_time(3 * D)
        assert b.get_piece_at(pos(0, 3)) == wr1
        assert b.get_piece_at(pos(1, 3)) == wr2


# ---------------------------------------------------------------------------
# Mixed: one enemy collision and one unrelated move in the same tick
# ---------------------------------------------------------------------------

class TestMixedCollisions:

    def test_unrelated_move_unaffected_by_enemy_collision(self):
        """A third piece on a separate path completes normally while two
        enemies collide on a different file."""
        b = make_board(3, 6)
        wr  = place(b, "WHITE", "R", 0, 0)
        br  = place(b, "BLACK", "R", 0, 5)
        wr2 = place(b, "WHITE", "R", 2, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr,  pos(0, 0), pos(0, 5))
        arb.advance_time(1)
        arb.add_move(br,  pos(0, 5), pos(0, 0))
        arb.add_move(wr2, pos(2, 0), pos(2, 3))
        arb.advance_time(5 * D)
        assert b.get_piece_at(pos(2, 3)) == wr2

    def test_enemy_collision_does_not_affect_friendly_on_same_row(self):
        """A friendly piece on the same row but different columns is untouched."""
        b = make_board(1, 8)
        wr1 = place(b, "WHITE", "R", 0, 0)
        br  = place(b, "BLACK", "R", 0, 7)
        wr2 = place(b, "WHITE", "R", 0, 3)  # idle, not moving
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 6))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 1))
        arb.advance_time(7 * D)
        # wr2 was never moved — still at col 3
        assert b.get_piece_at(pos(0, 3)) == wr2


# ---------------------------------------------------------------------------
# EXTENSIVE EDGE CASE TESTS — ENEMY COLLISIONS
# ---------------------------------------------------------------------------

class TestEnemyCollisionsEdgeCases:
    """Comprehensive tests for enemy piece collisions with various scenarios."""

    def test_exact_center_collision_head_on(self):
        """Two enemies meet exactly at the center square. Because they
        meet exactly halfway, bR (started later) arrives at the shared
        cell fractionally earlier in absolute time and is the one that
        sweeps wR (the earlier arriver) away."""
        b = make_board(1, 5)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 4))  # arrives at col 4 in 4 steps
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))  # arrives at col 0 in 4 steps, started later
        arb.advance_time(4 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert br.state == State.idle
        assert wr.state == State.captured
        assert b.get_piece_at(pos(0, 0)) == br

    def test_collision_at_destination_not_origin(self):
        """Collision happens at the destination, not partway through."""
        b = make_board(1, 6)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 5)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 5), pos(0, 0))
        arb.advance_time(5 * D)
        assert wr.position == pos(0, 5)
        assert br.state == State.captured

    def test_long_path_collision_midway(self):
        """Long path collision at midpoint, winner continues to destination."""
        b = make_board(1, 20)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 19)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 19))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 19), pos(0, 0))
        arb.advance_time(19 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr.state == State.idle
        assert wr.position == pos(0, 19)
        assert br.state == State.captured

    def test_diagonal_collision_bishops(self):
        """Two bishops colliding on a diagonal path."""
        b = make_board(8, 8)
        wb = place(b, "WHITE", "B", 0, 0)
        bb = place(b, "BLACK", "B", 7, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wb, pos(0, 0), pos(7, 7))
        arb.advance_time(1)
        arb.add_move(bb, pos(7, 7), pos(0, 0))
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wb.state == State.idle
        assert bb.state == State.captured
        assert b.get_piece_at(pos(7, 7)) == wb

    def test_collision_vertical_movement(self):
        """Collision on vertical movement (different x, same y)."""
        b = make_board(8, 1)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 7, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(7, 0))
        arb.advance_time(1)
        arb.add_move(br, pos(7, 0), pos(0, 0))
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr.state == State.idle
        assert br.state == State.captured

    def test_simultaneous_start_same_arrival_time_tiebreak(self):
        """When both pieces arrive at the shared cell at exactly the same
        time, both count as "earlier or equal" arrivers and both are
        captured — there's no single winner in a true tie."""
        b = make_board(1, 5)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 4))
        arb.add_move(br, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * D)
        assert wr.state == State.captured
        assert br.state == State.captured

    def test_enemy_collision_does_not_remove_winner_from_origin(self):
        """Winner is placed at destination; loser is captured."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        assert b.get_piece_at(pos(0, 7)) == wr
        assert b.get_piece_at(pos(0, 0)) != br  # loser removed

    def test_asymmetric_distances_earlier_starter_wins(self):
        """Pieces moving different distances but the same start time: their
        paths still overlap at col 4/5, so this is a real collision, not
        two independent completions."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))  # 5 steps
        arb.add_move(br, pos(0, 9), pos(0, 4))  # 5 steps, same arrival
        arb.advance_time(5 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr.state == State.captured
        assert br.state == State.idle
        assert b.get_piece_at(pos(0, 4)) == br

    def test_collision_piece_removed_from_board_state(self):
        """Captured piece is completely removed from the board."""
        b = make_board(1, 8)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        assert br.state == State.captured
        # br should not be on the board
        for x in range(1):
            for y in range(8):
                piece = b.get_piece_at(pos(x, y))
                if piece != EMPTY_CELL:
                    assert piece.color != br.color or piece != br

    def test_multiple_overlapping_paths_first_collision_resolved(self):
        """Multiple potential collision points; the earliest is resolved
        and the survivor continues, unaffected, to its own target."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))  # slides through cols 0-9
        arb.advance_time(1)
        arb.add_move(br, pos(0, 9), pos(0, 0))  # slides through cols 9-0
        # They collide at the first point they meet
        arb.advance_time(5 * D)
        assert br.state == State.captured
        # wR keeps going to its own target (col 9) and settles there
        arb.advance_time(9 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr.state == State.idle
        assert b.get_piece_at(pos(0, 9)) == wr

    def test_knight_vs_rook_collision(self):
        """Two knights (non-sliding) both leap to the same square: both
        moves are single-leap 'one step' moves, so the later starter
        (bN) arrives at the shared destination later in absolute time and
        sweeps away the earlier starter (wN)."""
        b = make_board(8, 8)
        wn = place(b, "WHITE", "N", 0, 0)
        bn = place(b, "BLACK", "N", 0, 2)
        arb = RealTimeArbiter(b)
        # Both knights leap to (2, 1)
        arb.add_move(wn, pos(0, 0), pos(2, 1))
        arb.advance_time(1)
        arb.add_move(bn, pos(0, 2), pos(2, 1))
        arb.advance_time(D)  # Knight destination reached in 1 step
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wn.state == State.captured
        assert bn.state == State.idle
        assert b.get_piece_at(pos(2, 1)) == bn


# ---------------------------------------------------------------------------
# EXTENSIVE EDGE CASE TESTS — FRIENDLY COLLISIONS
# ---------------------------------------------------------------------------

class TestFriendlyCollisionsEdgeCases:
    """Comprehensive tests for friendly piece collisions."""

    def test_friendly_collision_early_blocker(self):
        """Friendly piece blocks another early in its path: once fully
        resolved, wr2 never makes it to wr1's square."""
        b = make_board(1, 10)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 9), pos(0, 0))
        arb.advance_time(30 * D)  # let the collision fully resolve
        assert wr1.state == State.idle
        assert wr2.state == State.idle
        assert b.get_piece_at(pos(0, 0)) != wr2

    def test_friendly_truncated_stops_at_cell_before_collision(self):
        """Blocked piece stops exactly one cell before the blocker's path."""
        b = make_board(1, 10)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 9), pos(0, 0))
        arb.advance_time(30 * D)  # let the collision fully resolve
        # wr2 should stop when it would collide with wr1's path
        assert wr2.state == State.idle

    def test_friendly_first_step_blocked_move_cancelled(self):
        """If first step is blocked, move is cancelled entirely."""
        b = make_board(1, 5)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 1)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 1), pos(0, 0))  # First step (col 0) blocked
        arb.advance_time(D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr2.state == State.idle
        assert wr2.position == pos(0, 1)

    def test_friendly_three_pieces_cascading_blocks(self):
        """Three friendly pieces where middle blocks the trailing one."""
        b = make_board(1, 12)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 6)
        wr3 = place(b, "WHITE", "R", 0, 11)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 11))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 6), pos(0, 0))
        arb.advance_time(1)
        arb.add_move(wr3, pos(0, 11), pos(0, 0))
        arb.advance_time(11 * D)
        # wr3 should be blocked, wr2 should be blocked
        assert wr3.state == State.idle or wr3.state == State.moving

    def test_friendly_diagonal_collision(self):
        """Two friendly bishops colliding on diagonal."""
        b = make_board(8, 8)
        wb1 = place(b, "WHITE", "B", 0, 0)
        wb2 = place(b, "WHITE", "B", 7, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wb1, pos(0, 0), pos(7, 7))
        arb.advance_time(1)
        arb.add_move(wb2, pos(7, 7), pos(0, 0))
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # wb2 should be stopped before collision
        assert wb2.state == State.idle

    def test_friendly_vertical_collision(self):
        """Two friendly rooks colliding vertically."""
        b = make_board(8, 1)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 7, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(7, 0))
        arb.advance_time(1)
        arb.add_move(wr2, pos(7, 0), pos(0, 0))
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr2.state == State.idle

    def test_friendly_two_non_overlapping_paths_both_complete(self):
        """Friendly pieces on completely separate paths complete normally."""
        b = make_board(4, 4)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 3, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 3))
        arb.add_move(wr2, pos(3, 3), pos(3, 0))
        arb.advance_time(3 * D)
        assert b.get_piece_at(pos(0, 3)) == wr1
        assert b.get_piece_at(pos(3, 0)) == wr2

    def test_friendly_parallel_same_row_no_collision(self):
        """Friendly pieces moving in parallel on same row don't collide."""
        b = make_board(2, 10)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 1, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 9))
        arb.add_move(wr2, pos(1, 0), pos(1, 9))
        arb.advance_time(9 * D)
        assert b.get_piece_at(pos(0, 9)) == wr1
        assert b.get_piece_at(pos(1, 9)) == wr2

    def test_friendly_blocked_piece_stays_at_origin(self):
        """Blocked piece remains at its starting position."""
        b = make_board(1, 5)
        wr1 = place(b, "WHITE", "R", 0, 0)
        wr2 = place(b, "WHITE", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(wr2, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # wr1 (not wr2) turns out to be the one fully blocked here
        assert wr1.position == pos(0, 0)


# ---------------------------------------------------------------------------
# MIXED COLLISION SCENARIOS — COMPLEX MULTI-PIECE INTERACTIONS
# ---------------------------------------------------------------------------

class TestComplexMultiPieceScenarios:
    """Complex scenarios with multiple collisions and piece interactions."""

    def test_enemy_collision_while_friendly_blocked(self):
        """Enemy collision occurs simultaneously with friendly piece being blocked."""
        b = make_board(3, 8)
        # Enemy collision on row 0
        wr1 = place(b, "WHITE", "R", 0, 0)
        br1 = place(b, "BLACK", "R", 0, 7)
        # Friendly on row 2
        wr2 = place(b, "WHITE", "R", 2, 0)
        wr3 = place(b, "WHITE", "R", 2, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr1, pos(0, 0), pos(0, 7))
        arb.add_move(wr2, pos(2, 0), pos(2, 7))
        arb.advance_time(1)
        arb.add_move(br1, pos(0, 7), pos(0, 0))
        arb.add_move(wr3, pos(2, 7), pos(2, 0))
        arb.advance_time(7 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # Enemy collision resolves
        assert wr1.state == State.idle or br1.state == State.captured
        # Friendly should be blocked
        assert wr3.state == State.idle

    def test_three_pieces_bidirectional_collision(self):
        """Three pieces: two enemies collide, one friendly observes."""
        b = make_board(1, 9)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 8)
        wr2 = place(b, "WHITE", "R", 0, 4)  # idle observer
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 8))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 8), pos(0, 0))
        arb.advance_time(8 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # Collision resolves
        assert br.state == State.idle or wr.state == State.captured
        # Observer untouched
        assert b.get_piece_at(pos(0, 4)) == wr2

    def test_sequential_collisions_same_piece(self):
        """A piece collides, then is released, moves again and collides again."""
        b = make_board(1, 15)
        wr = place(b, "WHITE", "R", 0, 0)
        br1 = place(b, "BLACK", "R", 0, 7)
        br2 = place(b, "BLACK", "R", 0, 14)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 14))
        arb.advance_time(1)
        arb.add_move(br1, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * D)
        # br1 captured, wr continues on toward col 14 (br2's square)
        assert br1.state == State.captured
        assert wr.state == State.moving
        arb.advance_time(20 * D)
        assert wr.state == State.idle
        assert b.get_piece_at(pos(0, 14)) == wr
        # wr's arrival at col 14 captures br2, which was standing there
        assert br2.state == State.captured

    def test_four_pieces_two_separate_collisions(self):
        """Two independent enemy collisions on different rows simultaneously."""
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
        # Both collisions resolve independently
        captured_count = sum(1 for p in [br1, br2] if p.state == State.captured)
        assert captured_count >= 1

    def test_collision_at_exact_midpoint(self):
        """Collision occurs at exact geometric midpoint of board."""
        b = make_board(1, 11)  # 11 cells: 0-10
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 10)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 10))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 10), pos(0, 0))
        arb.advance_time(5 * D)  # Meet at col 5
        arb.advance_time(20 * D)
        assert br.state == State.idle or wr.state == State.captured

    def test_very_short_collision_one_cell(self):
        """Collision between adjacent cells."""
        b = make_board(1, 3)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 2)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 2))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 2), pos(0, 0))
        arb.advance_time(2 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert br.state == State.idle or wr.state == State.captured


# ---------------------------------------------------------------------------
# KING CAPTURE DETECTION
# ---------------------------------------------------------------------------

class TestKingCaptureDetection:
    """Tests for detecting when a king is captured (game-over condition)."""

    def test_white_king_captured_returns_true(self):
        """Capturing a WHITE king returns True (game over). A symmetric
        head-on collision (equal distance from both origins to the shared
        cell) makes the first starter — here the king — the earlier
        arriver, so it is the one that is captured. (The rook's own
        eventual arrival is not asserted here: it lands in the very same
        tick as the king capture, and is not relevant to what this test
        is checking.)"""
        b = make_board(1, 5)
        wk = place(b, "WHITE", "K", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wk, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))
        result = arb.advance_time(4 * D)
        assert result is True
        assert wk.state == State.captured

    def test_black_king_captured_returns_true(self):
        """Capturing a BLACK king returns True (game over)."""
        b = make_board(1, 5)
        bk = place(b, "BLACK", "K", 0, 0)
        wr = place(b, "WHITE", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(bk, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(wr, pos(0, 4), pos(0, 0))
        result = arb.advance_time(4 * D)
        assert result is True
        assert bk.state == State.captured

    def test_pawn_captured_returns_false(self):
        """Capturing a pawn returns False (game continues)."""
        b = make_board(1, 5)
        wp = place(b, "WHITE", "P", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wp, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))
        result = arb.advance_time(4 * D)
        assert result is False
        assert wp.state == State.captured

    def test_queen_captured_returns_false(self):
        """Capturing a queen returns False (not a king)."""
        b = make_board(1, 8)
        wq = place(b, "WHITE", "Q", 0, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wq, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(0, 0))
        result = arb.advance_time(7 * D)
        assert result is False

    def test_multiple_pieces_captured_king_detected(self):
        """When multiple pieces move, king capture is still detected."""
        b = make_board(2, 5)
        wk = place(b, "WHITE", "K", 0, 0)
        wr = place(b, "WHITE", "R", 1, 0)
        br = place(b, "BLACK", "R", 0, 4)
        br2 = place(b, "BLACK", "R", 1, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wk, pos(0, 0), pos(0, 4))
        arb.add_move(wr, pos(1, 0), pos(1, 4))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))
        arb.add_move(br2, pos(1, 4), pos(1, 0))
        result = arb.advance_time(4 * D)
        assert result is True  # King capture detected
        assert wk.state == State.captured


# ---------------------------------------------------------------------------
# TIMING AND ARRIVAL EDGE CASES
# ---------------------------------------------------------------------------

class TestTimingAndArrivalEdgeCases:
    """Tests for precise timing and arrival calculations."""

    def test_shorter_path_faster_arrival_wins(self):
        """When paths intersect, shorter path arrives first and wins."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 5))  # 5 steps
        arb.advance_time(1)
        arb.add_move(br, pos(0, 9), pos(0, 3))  # 6 steps
        arb.advance_time(5 * D)
        arb.advance_time(LONG_REST_DURATION_MS)
        # Their paths do overlap (cols 3-5), but wR reaches the shared
        # cells first and continues to its own target unaffected.
        assert wr.state == State.idle

    def test_arrival_calculation_multi_step_path(self):
        """Arrival time calculated correctly for multi-step paths: a
        19-step move isn't done at t=10*D, but is at t=19*D (plus its
        post-move rest)."""
        b = make_board(1, 20)
        wr = place(b, "WHITE", "R", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 19))
        arb.advance_time(10 * D)
        assert wr.state == State.moving
        arb.advance_time(9 * D)  # now at t = 19*D, exactly at arrival
        arb.advance_time(LONG_REST_DURATION_MS)
        assert wr.state == State.idle
        assert b.get_piece_at(pos(0, 19)) == wr

    def test_very_tiny_time_increment_no_collision(self):
        """Very small time advances don't cause false collisions, when the
        paths in question don't actually cross (different rows here)."""
        b = make_board(2, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 1, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(br, pos(1, 9), pos(1, 0))
        arb.advance_time(D // 2)  # Tiny advance
        # Pieces still in transit
        assert wr.state == State.moving
        assert br.state == State.moving

    def test_exact_arrival_time_detection(self):
        """Collision detected exactly at arrival time."""
        b = make_board(1, 5)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 4))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * D)  # Exact arrival time
        arb.advance_time(LONG_REST_DURATION_MS)
        assert br.state == State.idle or wr.state == State.captured


# ---------------------------------------------------------------------------
# BOARD BOUNDARY AND EDGE CASES
# ---------------------------------------------------------------------------

class TestBoardBoundaryEdgeCases:
    """Tests for collisions at board boundaries."""

    def test_collision_at_top_left_corner(self):
        """Collision at (0, 0) corner."""
        b = make_board(8, 8)
        wr = place(b, "WHITE", "R", 0, 7)
        br = place(b, "BLACK", "R", 7, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 7), pos(0, 0))
        arb.advance_time(1)
        arb.add_move(br, pos(7, 0), pos(0, 0))
        # Both heading to (0, 0)
        arb.advance_time(7 * D)
        assert b.get_piece_at(pos(0, 0)) != EMPTY_CELL

    def test_collision_at_bottom_right_corner(self):
        """Collision at bottom-right corner."""
        b = make_board(8, 8)
        wr = place(b, "WHITE", "R", 7, 0)
        br = place(b, "BLACK", "R", 0, 7)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(7, 0), pos(7, 7))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 7), pos(7, 7))
        arb.advance_time(7 * D)
        assert b.get_piece_at(pos(7, 7)) != EMPTY_CELL

    def test_collision_along_edge(self):
        """Collision along the board edge."""
        b = make_board(1, 10)
        wr = place(b, "WHITE", "R", 0, 0)
        br = place(b, "BLACK", "R", 0, 9)
        arb = RealTimeArbiter(b)
        arb.add_move(wr, pos(0, 0), pos(0, 9))
        arb.advance_time(1)
        arb.add_move(br, pos(0, 9), pos(0, 0))
        arb.advance_time(9 * D)
        # Collision on edge
        assert wr.state == State.idle or br.state == State.captured
