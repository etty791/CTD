from model.board import Board
from model.piece import Piece, State, Color
from model.position import Position
from events.event_bus import EventBus
from events.game_events import (
    GameEnded,
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)
from real_time.real_time_arbiter import RealTimeArbiter, DEFAULT_MOVE_DELAY_MS
from real_time.real_time_config import LONG_REST_DURATION_MS, SHORT_REST_DURATION_MS

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


class TestMoveStarted:
    def test_add_move_publishes_move_started(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveStarted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert received == [
            MoveStarted(1, rook.id, pos(0, 0), pos(0, 3), 0, 3 * DEFAULT_MOVE_DELAY_MS)
        ]

    def test_add_jump_publishes_move_started(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveStarted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_jump(knight, pos(0, 0))
        assert received == [
            MoveStarted(1, knight.id, pos(0, 0), pos(0, 0), 0, DEFAULT_MOVE_DELAY_MS)
        ]

    def test_rejected_move_does_not_publish(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        rook.state = State.moving
        bus = EventBus()
        received = []
        bus.subscribe(MoveStarted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert received == []


class TestMoveCompleted:
    def test_arrival_publishes_move_completed(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveCompleted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert received == [MoveCompleted(1, rook.id, rook.type, rook.color, pos(0, 0), pos(0, 3))]

    def test_not_yet_arrived_does_not_publish(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveCompleted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert received == []


class TestPieceCaptured:
    def test_arrival_capture_publishes_piece_captured(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        pawn = place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        received = []
        bus.subscribe(PieceCaptured, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert received == [PieceCaptured(pawn.id, pawn.type, pawn.color, pos(0, 3), 1)]

    def test_in_flight_capture_publishes_piece_captured(self):
        b = empty_board(1, 8)
        white_rook = place(b, "WHITE", "ROOK", 0, 0)
        black_rook = place(b, "BLACK", "ROOK", 0, 7)
        bus = EventBus()
        received = []
        bus.subscribe(PieceCaptured, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(white_rook, pos(0, 0), pos(0, 7))
        arb.advance_time(1)
        arb.add_move(black_rook, pos(0, 7), pos(0, 0))
        arb.advance_time(7 * DEFAULT_MOVE_DELAY_MS)
        assert len(received) == 1
        assert received[0].piece_id in (white_rook.id, black_rook.id)


class TestGameEnded:
    def test_king_capture_publishes_game_ended_with_winner(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "KING", 0, 3)
        bus = EventBus()
        received = []
        bus.subscribe(GameEnded, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert received == [GameEnded(Color.WHITE)]

    def test_non_king_capture_does_not_publish_game_ended(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        received = []
        bus.subscribe(GameEnded, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert received == []


class TestMoveTruncated:
    """A move shortened by a same-color blocker is still in flight -- but
    toward a nearer square, arriving sooner."""

    def test_blocked_move_publishes_its_new_target_and_arrival(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)          # crosses column 3 at t=3000
        late = place(b, "WHITE", "ROOK", 5, 3)   # reaches column 3's row 0 at t=5000
        bus = EventBus()
        received = []
        bus.subscribe(MoveTruncated, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(b.get_piece_at(pos(0, 0)), pos(0, 0), pos(0, 5))
        arb.add_move(late, pos(5, 3), pos(0, 3))

        arb.advance_time(1)

        assert received == [
            MoveTruncated(2, late.id, pos(1, 3), 4 * DEFAULT_MOVE_DELAY_MS, in_flight=True)
        ]

    def test_unobstructed_move_publishes_nothing(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveTruncated, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))

        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        assert received == []


class TestMoveAborted:
    """A move that ends without the piece ever reaching a new cell."""

    def test_move_invalidated_by_arrival_time_publishes_aborted(self):
        # A one-square move's vacate time equals its arrival time, so the
        # "nearest free square walking backwards from target" retreat
        # lands it right back on its own origin - the observable result is
        # identical to the old MoveAborted-at-origin behavior, but per the
        # vacate rule it is still a "vacated piece that failed
        # revalidation", so the event fired is MoveTruncated(target=origin).
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "WHITE", "PAWN", 0, 1)  # own piece on the (one-square) target
        bus = EventBus()
        aborted = []
        truncated = []
        bus.subscribe(MoveAborted, aborted.append)
        bus.subscribe(MoveTruncated, truncated.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 1))

        arb.advance_time(DEFAULT_MOVE_DELAY_MS)

        assert aborted == []
        assert truncated == [
            MoveTruncated(1, rook.id, pos(0, 0), arb.clock, in_flight=False)
        ]
        assert b.get_piece_at(pos(0, 0)) is rook

    def test_multi_square_invalidation_publishes_truncated_not_aborted(self):
        # A multi-square move has already vacated its origin by the time
        # it arrives, so per the vacate-on-move rule it never returns
        # there: this now degenerates to a MoveTruncated at the nearest
        # free square walking backwards from the target, not a MoveAborted.
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "WHITE", "PAWN", 0, 3)  # own piece on the target square
        bus = EventBus()
        aborted = []
        truncated = []
        bus.subscribe(MoveAborted, aborted.append)
        bus.subscribe(MoveTruncated, truncated.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))

        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        assert aborted == []
        assert truncated == [
            MoveTruncated(1, rook.id, pos(0, 2), arb.clock, in_flight=False)
        ]
        assert b.get_piece_at(pos(0, 2)) is rook

    def test_move_blocked_before_its_first_step_publishes_aborted(self):
        # Both rooks want the same square and would reach it at the same
        # instant, one step in. left's move was added first, so the
        # deterministic move_id tie-break has it win the race and keep
        # going; only right is blocked before it can take even that step.
        b = empty_board()
        left = place(b, "WHITE", "ROOK", 0, 0)
        right = place(b, "WHITE", "ROOK", 0, 2)
        bus = EventBus()
        received = []
        bus.subscribe(MoveAborted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(left, pos(0, 0), pos(0, 3))
        arb.add_move(right, pos(0, 2), pos(0, 1))

        arb.advance_time(1)

        assert {(e.piece_id, e.position) for e in received} == {
            (right.id, pos(0, 2)),
        }

    def test_completed_move_publishes_nothing(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveAborted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))

        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        assert received == []


class TestRestEnded:
    def test_long_rest_expiry_publishes_rest_ended_at_the_new_square(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(RestEnded, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 1))

        arb.advance_time(DEFAULT_MOVE_DELAY_MS)
        assert received == []  # arrived, but still resting

        arb.advance_time(LONG_REST_DURATION_MS)

        assert received == [RestEnded(rook.id, pos(0, 1))]

    def test_jump_publishes_rest_ended_after_the_short_rest(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 4, 4)
        bus = EventBus()
        received = []
        bus.subscribe(RestEnded, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_jump(knight, pos(4, 4))

        arb.advance_time(DEFAULT_MOVE_DELAY_MS + SHORT_REST_DURATION_MS)

        assert received == [RestEnded(knight.id, pos(4, 4))]


class TestNoEventBus:
    def test_arbiter_without_event_bus_is_a_no_op(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
