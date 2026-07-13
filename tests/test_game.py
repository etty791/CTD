import pytest
from unittest.mock import MagicMock, patch
from model.board import Board
from model.piece import Piece, Color, PieceType
from model.position import Position
from rules.rules_engine import MoveValidation
from game_engine.game import KungFuChessGame

EMPTY = "."


def empty_board(rows=8, cols=8):
    return [[EMPTY] * cols for _ in range(rows)]


KIND_MAP = {"PAWN": "P", "KNIGHT": "N", "BISHOP": "B", "ROOK": "R", "QUEEN": "Q", "KING": "K"}

def make_piece(color, kind, x, y):
    c = color[0].lower()
    k = KIND_MAP[kind]
    return Piece(f"{c}{k}", c, k, Position(x, y))


def make_game_with_piece(color="WHITE", kind="ROOK", x=0, y=0):
    grid = empty_board()
    piece = make_piece(color, kind, x, y)
    grid[x][y] = piece
    return KungFuChessGame(grid), piece


def pos(x, y):
    return Position(x, y)


# ── move_request: same-origin-as-target ──────────────────────────────────────

class TestMoveRequestSameSquare:
    def test_returns_false(self):
        game, _ = make_game_with_piece()
        assert game.move_request(pos(0, 0), pos(0, 0)) is False


# ── move_request: game already over ──────────────────────────────────────────

class TestMoveRequestGameOver:
    def setup_method(self):
        self.game, _ = make_game_with_piece()
        self.game.finish_game()

    def test_returns_invalid(self):
        result = self.game.move_request(pos(0, 0), pos(0, 5))
        assert not result.is_valid

    def test_reason_is_game_over(self):
        result = self.game.move_request(pos(0, 0), pos(0, 5))
        assert result.reason == "game_over"


# ── move_request: invalid move (rules engine rejects) ────────────────────────

class TestMoveRequestInvalidMove:
    def test_rook_diagonal_is_invalid(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        result = game.move_request(pos(0, 0), pos(3, 3))
        assert not result.is_valid
        assert result.reason == "illegal_piece_move"

    def test_reason_propagated_from_rules(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        result = game.move_request(pos(0, 0), pos(3, 3))
        assert result.reason != "game_over"


# ── move_request: valid move, arbiter accepts ─────────────────────────────────

class TestMoveRequestValidAccepted:
    def test_returns_valid(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        result = game.move_request(pos(0, 0), pos(0, 5))
        assert result.is_valid
        assert result.reason == "ok"


# ── move_request: valid move, arbiter rejects (piece already moving) ──────────

class TestMoveRequestArbiterRejects:
    def test_returns_invalid_move(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        # first move queues the piece
        game.move_request(pos(0, 0), pos(0, 5))
        # second move from same origin while piece is in-flight
        result = game.move_request(pos(0, 0), pos(0, 3))
        assert not result.is_valid
        assert result.reason == "invalid_move"


# ── finish_game ───────────────────────────────────────────────────────────────

class TestFinishGame:
    def test_sets_game_inactive(self):
        game, _ = make_game_with_piece()
        game.finish_game()
        assert not game.game_active

    def test_subsequent_moves_rejected(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        game.finish_game()
        assert not game.move_request(pos(0, 0), pos(0, 5)).is_valid


# ── wait ──────────────────────────────────────────────────────────────────────

class TestWait:
    def test_wait_advances_clock(self):
        game, _ = make_game_with_piece("WHITE", "ROOK", 0, 0)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(500)
        assert game.rta.clock == 500

    def test_wait_executes_arrived_move(self):
        game, piece = make_game_with_piece("WHITE", "ROOK", 0, 0)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(5001)  # distance=5 → 5000 ms
        assert game.board.get_piece_at(pos(0, 5)) == piece

    def test_wait_king_captured_ends_game(self):
        grid = empty_board()
        white_rook = make_piece("WHITE", "ROOK", 0, 0)
        black_king = make_piece("BLACK", "KING", 0, 5)
        grid[0][0] = white_rook
        grid[0][5] = black_king
        game = KungFuChessGame(grid)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(5001)
        assert not game.game_active

    def test_wait_no_king_captured_game_continues(self):
        grid = empty_board()
        white_rook = make_piece("WHITE", "ROOK", 0, 0)
        black_pawn = make_piece("BLACK", "PAWN", 0, 5)
        grid[0][0] = white_rook
        grid[0][5] = black_pawn
        game = KungFuChessGame(grid)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(5001)
        assert game.game_active

    def test_wait_move_not_yet_arrived(self):
        game, piece = make_game_with_piece("WHITE", "ROOK", 0, 0)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(100)  # not enough time
        assert game.board.get_piece_at(pos(0, 0)) == piece
        assert game.board.get_piece_at(pos(0, 5)) == EMPTY

    def test_multiple_waits_accumulate(self):
        game, piece = make_game_with_piece("WHITE", "ROOK", 0, 0)
        game.move_request(pos(0, 0), pos(0, 5))
        game.wait(2000)
        game.wait(3001)
        assert game.board.get_piece_at(pos(0, 5)) == piece


# ── initial state ─────────────────────────────────────────────────────────────

class TestInitialState:
    def test_game_active_on_init(self):
        game, _ = make_game_with_piece()
        assert game.game_active

    def test_board_initialized(self):
        game, piece = make_game_with_piece("WHITE", "ROOK", 3, 3)
        assert game.board.get_piece_at(pos(3, 3)) == piece
