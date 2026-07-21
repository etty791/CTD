from model.board import Board
from model.piece import Piece, State, Color
from model.position import Position
from events.event_bus import EventBus
from events.game_events import GameEnded, MoveCompleted, MoveStarted, PieceCaptured
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


class TestMoveStarted:
    def test_add_move_publishes_move_started(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveStarted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        assert received == [MoveStarted(1, rook.id, pos(0, 0), pos(0, 3))]

    def test_add_jump_publishes_move_started(self):
        b = empty_board()
        knight = place(b, "WHITE", "KNIGHT", 0, 0)
        bus = EventBus()
        received = []
        bus.subscribe(MoveStarted, received.append)
        arb = RealTimeArbiter(b, bus)
        arb.add_jump(knight, pos(0, 0))
        assert received == [MoveStarted(1, knight.id, pos(0, 0), pos(0, 0))]

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


class TestNoEventBus:
    def test_arbiter_without_event_bus_is_a_no_op(self):
        b = empty_board()
        rook = place(b, "WHITE", "ROOK", 0, 0)
        arb = RealTimeArbiter(b)
        arb.add_move(rook, pos(0, 0), pos(0, 3))
        arb.advance_time(3 * DEFAULT_MOVE_DELAY_MS)
