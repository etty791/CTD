from model.board import Board
from model.piece import Piece, Color
from model.position import Position
from events.event_bus import EventBus
from events.game_events import ScoreChanged
from game_engine.score_tracker import ScoreTracker
from real_time.real_time_arbiter import RealTimeArbiter, DEFAULT_MOVE_DELAY_MS
from real_time.real_time_config import LONG_REST_DURATION_MS

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


class TestScoreTracker:
    def test_fresh_tracker_scores_are_zero(self):
        bus = EventBus()
        scores = ScoreTracker(bus)
        assert scores.get_score(Color.WHITE) == 0
        assert scores.get_score(Color.BLACK) == 0

    def test_pawn_capture_awards_one_point(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        scores = ScoreTracker(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert scores.get_score(Color.WHITE) == 1
        assert scores.get_score(Color.BLACK) == 0

    def test_each_piece_type_awards_its_standard_value(self):
        expected = {
            "PAWN": 1, "KNIGHT": 3, "BISHOP": 3, "ROOK": 5, "QUEEN": 9,
        }
        for type_name, value in expected.items():
            b = empty_board()
            rook = place(b, "WHITE", "ROOK", 0, 0)
            place(b, "BLACK", type_name, 0, 3)
            bus = EventBus()
            scores = ScoreTracker(bus)
            arb = RealTimeArbiter(b, bus)
            arb.add_move(rook, pos(0, 0), pos(0, 3))
            arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
            assert scores.get_score(Color.WHITE) == value, f"{type_name} should award {value}"

    def test_capture_publishes_score_changed_with_cumulative_score(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "QUEEN", 0, 3)
        bus = EventBus()
        received = []
        bus.subscribe(ScoreChanged, received.append)
        ScoreTracker(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert received == [ScoreChanged(Color.WHITE, 9)]

    def test_cumulative_score_across_multiple_captures(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        place(b, "BLACK", "KNIGHT", 0, 6)
        bus = EventBus()
        scores = ScoreTracker(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(LONG_REST_DURATION_MS)
        arb.add_move(rook, pos(0, 3), pos(0, 6))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        assert scores.get_score(Color.WHITE) == 4  # pawn (1) + knight (3)

    def test_king_capture_does_not_go_through_score_tracker(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "KING", 0, 3)
        bus = EventBus()
        scores = ScoreTracker(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS) is True
        assert scores.get_score(Color.WHITE) == 0
        assert scores.get_score(Color.BLACK) == 0

    def test_never_given_events_stays_empty(self):
        bus = EventBus()
        scores = ScoreTracker(bus)
        assert scores.get_score(Color.WHITE) == 0
        assert scores.get_score(Color.BLACK) == 0
