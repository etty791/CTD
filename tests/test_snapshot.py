from model.board import Board
from model.piece import Piece, Color
from model.position import Position
from game_engine.snapshot import GameSnapshot
from game_engine.score_tracker import ScoreTracker
from events.event_bus import EventBus
from real_time.real_time_arbiter import RealTimeArbiter, DEFAULT_MOVE_DELAY_MS

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


class TestGetAllPiecesMotion:
    def test_idle_piece_has_no_move_times(self):
        b = empty_board()
        place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        snapshot = GameSnapshot(b, arb, scores)

        dto = snapshot.get_all_pieces()[0]

        assert dto.move_start_ms is None
        assert dto.move_arrival_ms is None
        assert dto.progress == 0.0

    def test_moving_piece_carries_its_moves_absolute_times(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(DEFAULT_MOVE_DELAY_MS)  # one square into a 3-square move
        snapshot = GameSnapshot(b, arb, scores)

        dto = snapshot.get_all_pieces()[0]

        assert dto.move_start_ms == 0
        assert dto.move_arrival_ms == 3 * DEFAULT_MOVE_DELAY_MS
        assert dto.progress == DEFAULT_MOVE_DELAY_MS / (3 * DEFAULT_MOVE_DELAY_MS)


class TestGetClockMs:
    def test_reports_the_arbiters_clock(self):
        b = empty_board()
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        snapshot = GameSnapshot(b, arb, scores)
        assert snapshot.get_clock_ms() == 0

        arb.advance_time(1234)

        assert snapshot.get_clock_ms() == 1234


class TestGetScores:
    def test_fresh_game_scores_are_zero(self):
        b = empty_board()
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        snapshot = GameSnapshot(b, arb, scores)
        assert snapshot.get_scores() == {Color.WHITE: 0, Color.BLACK: 0}

    def test_reflects_score_tracker_after_capture(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        pawn = place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        snapshot = GameSnapshot(b, arb, scores)
        assert snapshot.get_scores() == {Color.WHITE: 1, Color.BLACK: 0}

    def test_returned_dict_is_a_copy(self):
        b = empty_board()
        bus = EventBus()
        arb = RealTimeArbiter(b, bus)
        scores = ScoreTracker(bus)
        snapshot = GameSnapshot(b, arb, scores)
        scores_dict = snapshot.get_scores()
        scores_dict[Color.WHITE] = 999
        assert scores.get_score(Color.WHITE) == 0
