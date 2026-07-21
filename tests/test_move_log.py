from model.board import Board
from model.piece import Piece, PieceType, Color
from model.position import Position
from events.event_bus import EventBus
from game_engine.move_log import MoveLog
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


class TestMoveLog:
    def test_never_given_events_stays_empty(self):
        bus = EventBus()
        log = MoveLog(bus)
        assert log.get_log() == []

    def test_single_move_produces_one_entry(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        log = MoveLog(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        entries = log.get_log()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.piece_id == rook.id
        assert entry.piece_type == PieceType.ROOK
        assert entry.color == Color.WHITE
        assert entry.src == pos(0, 0)
        assert entry.dst == pos(0, 3)
        assert entry.was_capture is False

    def test_sequence_of_moves_produces_entries_in_order(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bishop = place(b, "BLACK", "BISHOP", 7, 0)
        bus = EventBus()
        log = MoveLog(bus)
        arb = RealTimeArbiter(b, bus)

        # Both moves are equal-distance slides, so both arrive on the same
        # tick - insertion order (rook added first) determines log order.
        arb.add_move(rook, pos(0, 0), pos(0, 2))
        arb.add_move(bishop, pos(7, 0), pos(5, 2))
        arb.advance_time(2 * DEFAULT_MOVE_DELAY_MS)

        entries = log.get_log()
        assert [e.piece_id for e in entries] == [rook.id, bishop.id]

    def test_captured_move_entry_reflects_was_capture(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        log = MoveLog(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        entries = log.get_log()
        assert len(entries) == 1
        assert entries[0].was_capture is True

    def test_non_capturing_move_after_capturing_move_is_not_marked(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        place(b, "BLACK", "PAWN", 0, 3)
        bus = EventBus()
        log = MoveLog(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
        arb.advance_time(LONG_REST_DURATION_MS)
        arb.add_move(rook, pos(0, 3), pos(0, 5))
        arb.advance_time(2 * DEFAULT_MOVE_DELAY_MS)

        entries = log.get_log()
        assert len(entries) == 2
        assert entries[0].was_capture is True
        assert entries[1].was_capture is False

    def test_get_log_returns_a_copy(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        log = MoveLog(bus)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)

        entries = log.get_log()
        entries.append("bogus")
        assert len(log.get_log()) == 1
