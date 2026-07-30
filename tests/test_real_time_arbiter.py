import pytest
from unittest.mock import MagicMock
from model.board import Board
from model.piece import Piece, PieceType, State, Color
from model.position import Position
from events.event_bus import EventBus
from events.game_events import PieceCaptured
from real_time.real_time_arbiter import (
    RealTimeArbiter,
    DEFAULT_MOVE_DELAY_MS,
    LONG_REST_DURATION_MS,
    SHORT_REST_DURATION_MS,
)

EMPTY = None


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
        
        # Corrected to a valid diagonal target: (5, 5)
        arb.add_move(bishop, pos(0, 0), pos(5, 5)) 
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
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)  # only 1 step worth, needs 3
        # Past its first step, the rook has vacated its origin (it is
        # in-flight, tracked via pending_moves/snapshot, not the board)
        # but has not arrived at its target either.
        assert b.get_piece_at(pos(0, 0)) == EMPTY
        assert b.get_piece_at(pos(0, 3)) == EMPTY

    def test_move_applied_at_arrival(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(0, 3)) == rook
        assert b.get_piece_at(pos(0, 0)) == EMPTY

    def test_piece_state_long_rest_after_arrival_then_idle(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert rook.state == State.long_rest
        arb.advance_time(LONG_REST_DURATION_MS)
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


class TestJump:
    def test_jump_last_1000_ms_and_completes_at_arrival(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 2, 2)
        arb = RealTimeArbiter(b)

        assert arb.add_jump(knight, pos(2, 2)) is True
        arb.advance_time(DEFAULT_MOVE_DELAY_MS - 1)
        assert knight.state == State.airborne
        assert b.get_piece_at(pos(2, 2)) == knight

        arb.advance_time(1)
        assert knight.state == State.short_rest
        assert b.get_piece_at(pos(2, 2)) == knight
        assert len(arb.pending_moves) == 0

        arb.advance_time(SHORT_REST_DURATION_MS)
        assert knight.state == State.idle

    def test_jump_keeps_piece_on_same_logical_cell(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 3, 3)
        arb = RealTimeArbiter(b)

        arb.add_jump(knight, pos(3, 3))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(SHORT_REST_DURATION_MS)

        assert b.get_piece_at(pos(3, 3)) == knight
        assert knight.position == pos(3, 3)
        assert knight.state == State.idle

    def test_airborne_piece_captures_enemy_moving_piece_during_jump_window(self):
        b = empty_board()
        airborne = place(b, "WHITE", "KNIGHT", 2, 2)
        enemy = place(b, "BLACK", "ROOK", 2, 3)
        arb = RealTimeArbiter(b)

        arb.add_jump(airborne, pos(2, 2))
        arb.add_move(enemy, pos(2, 3), pos(2, 2))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)

        assert b.get_piece_at(pos(2, 2)) == airborne
        assert b.get_piece_at(pos(2, 3)) == EMPTY
        assert enemy.state == State.captured

        arb.advance_time(SHORT_REST_DURATION_MS)
        assert airborne.state == State.idle

    def test_jump_lands_normally_when_no_enemy_arrives(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 4, 4)
        arb = RealTimeArbiter(b)

        arb.add_jump(knight, pos(4, 4))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)

        assert knight.state == State.short_rest
        assert b.get_piece_at(pos(4, 4)) == knight

        arb.advance_time(SHORT_REST_DURATION_MS)
        assert knight.state == State.idle

    def test_moving_piece_cannot_jump(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)

        assert arb.add_move(rook, pos(0, 0), pos(0, 2)) is True
        assert arb.add_jump(rook, pos(0, 0)) is False
        assert len(arb.pending_moves) == 1
        assert rook.state == State.moving

    def test_captured_piece_cannot_jump(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 1, 1)
        arb = RealTimeArbiter(b)

        knight.state = State.captured
        assert arb.add_jump(knight, pos(1, 1)) is False
        assert len(arb.pending_moves) == 0


class TestCollision:
    def test_collision_at_exact_tie_deterministic_survivor(self):
        # Both rooks are 3 steps from the shared cell and start together, an
        # exact arrival-time tie. rook1's move was added first, so the
        # deterministic move_id tie-break has it survive at the cell and
        # capture rook2 rather than both being destroyed.
        b = empty_board()
        rook1 = place(b, "WHITE", "ROOK", 0, 3)
        rook2 = place(b, "BLACK", "ROOK", 6, 3)
        arb = RealTimeArbiter(b)
        arb.add_move(rook1, pos(0, 3), pos(3, 3))
        arb.add_move(rook2, pos(6, 3), pos(3, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert b.get_piece_at(pos(3, 3)) == rook1

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
        # The rook vacated (0, 0) long before arrival and, per the
        # vacate-on-move rule, never returns there: it retreats to the
        # nearest free square walking backwards from its target along its
        # own path, which is (0, 2).
        assert b.get_piece_at(pos(0, 0)) == EMPTY
        assert b.get_piece_at(pos(0, 2)) == rook

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
        # rook2 is only 2 of its 5 steps in - not yet arrived, and past
        # its first step it has vacated (7, 0) rather than still sitting
        # there.
        assert b.get_piece_at(pos(7, 0)) == EMPTY
        assert b.get_piece_at(pos(7, 5)) == EMPTY


class TestRest:
    def _arb_with_rook(self, x=0, y=0):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", x, y)
        return b, rook, RealTimeArbiter(b)

    def test_move_arrival_enters_long_rest(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 1))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert rook.state == State.long_rest

    def test_jump_landing_enters_short_rest(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_jump(rook, pos(0, 0))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert rook.state == State.short_rest

    def test_long_rest_boundary_is_inclusive(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 1))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(LONG_REST_DURATION_MS - 1)
        assert rook.state == State.long_rest
        arb.advance_time(1)
        assert rook.state == State.idle

    def test_short_rest_boundary_is_inclusive(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_jump(rook, pos(0, 0))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(SHORT_REST_DURATION_MS - 1)
        assert rook.state == State.short_rest
        arb.advance_time(1)
        assert rook.state == State.idle

    def test_add_move_rejected_while_resting(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 1))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert arb.add_move(rook, pos(0, 1), pos(0, 2)) is False
        assert len(arb.pending_moves) == 0
        assert rook.state == State.long_rest

    def test_add_jump_rejected_while_resting(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_jump(rook, pos(0, 0))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert arb.add_jump(rook, pos(0, 0)) is False
        assert len(arb.pending_moves) == 0
        assert rook.state == State.short_rest

    def test_rest_expires_within_single_large_advance(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 1))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS)
        assert rook.state == State.idle

    def test_rest_anchored_to_arrival_not_final_clock(self):
        # Arrival at t=1000, rest spans 1000..3000 - a single jump to
        # t=5000 must release the piece, not restart the rest at 5000.
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 1))
        arb.advance_time(5 * DEFAULT_MOVE_DELAY_MS)
        assert rook.state == State.idle

    def test_truncated_at_origin_enters_long_rest(self):
        b = empty_board()
        mover = place(b, "WHITE", "ROOK", 0, 0)
        blocker = place(b, "WHITE", "ROOK", 1, 1)
        arb = RealTimeArbiter(b)
        # blocker reaches (0, 1) - mover's first step - just before the
        # mover does, so the mover is truncated back onto its origin
        arb.add_move(blocker, pos(1, 1), pos(0, 1))
        arb.advance_time(1)
        arb.add_move(mover, pos(0, 0), pos(0, 3))
        arb.advance_time(1)  # collision fates resolve eagerly
        assert b.get_piece_at(pos(0, 0)) == mover
        assert mover.state == State.long_rest
        # rest is anchored at the move's start_time (t=1)
        arb.advance_time(LONG_REST_DURATION_MS)
        assert mover.state == State.idle
        assert arb.add_move(mover, pos(0, 0), pos(1, 0)) is True

    def test_revalidation_failure_enters_long_rest(self):
        b, rook, arb = self._arb_with_rook()
        arb.add_move(rook, pos(0, 0), pos(0, 5))
        place(b, "WHITE", "PAWN", 0, 3)  # block the path before arrival
        rook.state = State.moving
        arb.advance_time(5 * DEFAULT_MOVE_DELAY_MS)
        # Vacated long before arrival, so it doesn't return to (0, 0) - it
        # retreats to the nearest free square walking backwards from its
        # target, (0, 4) (the blocker sits further back, at (0, 3)).
        assert b.get_piece_at(pos(0, 0)) == EMPTY
        assert b.get_piece_at(pos(0, 4)) == rook
        assert rook.state == State.long_rest
        arb.advance_time(LONG_REST_DURATION_MS)
        assert rook.state == State.idle


class TestCapturedWhileResting:
    def test_captured_while_resting_stays_captured(self):
        b = empty_board()
        white = place(b, "WHITE", "ROOK", 0, 3)
        black = place(b, "BLACK", "ROOK", 0, 1)
        arb = RealTimeArbiter(b)
        # white moves one square and rests 1000..3000 at (0, 2)
        arb.add_move(white, pos(0, 3), pos(0, 2))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert white.state == State.long_rest
        # black lands on the resting white at t=2000
        arb.add_move(black, pos(0, 1), pos(0, 2))
        arb.advance_time(2 * DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS)
        assert b.get_piece_at(pos(0, 2)) == black
        assert white.state == State.captured


class TestGhostMoveRegression:
    """A piece killed mid-flight must not leave its own pending Move
    behind - the "ghost move" bug: without dropping it, a corpse could
    still truncate/capture as if it were alive, and be captured a second
    time itself (double-scoring its own value)."""

    def test_captured_piece_drops_its_own_pending_move(self):
        b = empty_board(rows=1, cols=8)
        black_rook = place(b, "BLACK", "ROOK", 0, 0)
        white_rook = place(b, "WHITE", "ROOK", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_move(black_rook, pos(0, 0), pos(0, 7))   # long trip, arrives late
        arb.advance_time(1)
        arb.add_move(white_rook, pos(0, 4), pos(0, 0))   # sweeps onto black's origin
        arb.advance_time(4 * DEFAULT_MOVE_DELAY_MS)
        assert black_rook.state == State.captured
        assert arb.pending_moves == []

    def test_sweeping_a_corpses_old_path_does_not_recapture_it(self):
        b = empty_board(rows=1, cols=8)
        black_rook = place(b, "BLACK", "ROOK", 0, 0)
        white_killer = place(b, "WHITE", "ROOK", 0, 4)
        white_sweeper = place(b, "WHITE", "ROOK", 0, 6)
        bus = EventBus()
        captured = []
        bus.subscribe(PieceCaptured, captured.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(black_rook, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(white_killer, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * DEFAULT_MOVE_DELAY_MS)
        assert black_rook.state == State.captured
        assert len(captured) == 1
        # A third piece crosses straight through where the dead rook's
        # move used to be heading (its stale path, had it not been
        # dropped, would still claim to occupy col 7).
        arb.add_move(white_sweeper, pos(0, 6), pos(0, 7))
        arb.advance_time(2 * DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS)
        assert len(captured) == 1
        assert b.get_piece_at(pos(0, 7)) == white_sweeper

    def test_dead_piece_no_longer_truncates_a_friendly_mover(self):
        b = empty_board(rows=1, cols=8)
        black_rook = place(b, "BLACK", "ROOK", 0, 0)
        white_killer = place(b, "WHITE", "ROOK", 0, 4)
        black_second = place(b, "BLACK", "ROOK", 0, 6)
        arb = RealTimeArbiter(b)
        arb.add_move(black_rook, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(white_killer, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * DEFAULT_MOVE_DELAY_MS)
        assert black_rook.state == State.captured
        # A second black piece crosses the dead rook's old path - it must
        # not be truncated by a corpse that no longer has a pending move.
        assert arb.add_move(black_second, pos(0, 6), pos(0, 7)) is True
        arb.advance_time(DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS)
        assert b.get_piece_at(pos(0, 7)) == black_second
        assert black_second.state == State.idle

    def test_jump_never_vacates_but_stops_intercepting_once_landed(self):
        """An airborne piece is never vacated - it stays on the board for
        its whole jump window (one DEFAULT_MOVE_DELAY_MS), still able to
        intercept a mover that enters its square during that window
        (real_time/collision_fates.py's airborne branch, gated on
        a.start_time <= t <= a.arrival_time). Once that window closes it
        lands and rests like any other piece - it does not go on guarding
        its square forever. Here mover's own path only reaches (0, 0) on
        its very last step, well after the jump has already landed (a
        4-square slide starting 1ms after the jump takes 4000ms to arrive,
        against the jump's 1000ms window), so this is an ordinary capture
        of a resting piece, not an interception.

        (This inverts what the test asserted before phase 2's event-heap
        scheduler: driven by one advance_time(4000) call, the legacy tick
        sweep bumped its clock to the end of that call before checking
        anything, so `jumper.state` was still State.airborne - never having
        had the chance to transition to short_rest partway through - when
        the interception branch ran. That let the jumper "intercept" a
        mover arriving 3 full seconds after its own airborne window
        actually closed, which is a scheduling artifact, not a rule a piece
        should have. Confirmed by replaying the same scenario through the
        legacy tick sweep at 1 ms granularity, which reaches the identical
        outcome asserted below.)"""
        b = empty_board(rows=1, cols=8)
        jumper = place(b, "BLACK", "ROOK", 0, 0)
        mover = place(b, "WHITE", "ROOK", 0, 4)
        arb = RealTimeArbiter(b)
        arb.add_jump(jumper, pos(0, 0))
        arb.advance_time(1)
        # An airborne piece is never vacated - it stays on the board for
        # its whole jump window, still able to intercept.
        assert b.get_piece_at(pos(0, 0)) == jumper
        arb.add_move(mover, pos(0, 4), pos(0, 0))
        arb.advance_time(4 * DEFAULT_MOVE_DELAY_MS)
        assert jumper.state == State.captured
        assert mover.state != State.captured
        assert b.get_piece_at(pos(0, 0)) == mover
