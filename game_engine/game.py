from typing import Optional

from model.board import Board, EMPTY_CELL
from model.piece import Color
from model.position import Position
from game_engine.snapshot import GameSnapshot
from game_engine.score_tracker import ScoreTracker
from game_engine.move_log import MoveLog
from rules.rules_engine import MoveValidation, validate_move
from rules.rules_config import MoveReason
from real_time.real_time_arbiter import RealTimeArbiter
from events.event_bus import EventBus
from events.game_events import GameStarted


class KungFuChessGame:
    def __init__(self, initial_board=None):
        if initial_board is None:
            initial_board = Board.generate_standard_grid()
        self.board = Board(initial_board)
        self.events = EventBus()
        self.rta=RealTimeArbiter(self.board, self.events)
        self.scores = ScoreTracker(self.events)
        self.move_log = MoveLog(self.events)
        self.game_active = True
        self.events.publish(GameStarted())

    def move_request(self, origin, target):
        # if origin == target:
        #     return False
        if not self.game_active:
            return MoveValidation(False, reason=MoveReason.GAME_OVER)
        is_valid_move = validate_move(self.board, origin, target)
        if is_valid_move.is_valid:
            piece = self.board.get_piece_at(origin)
            if piece.state.is_resting():
                return MoveValidation(False, reason=MoveReason.PIECE_RESTING)
            if not self.rta.add_move(piece, origin, target):
                return MoveValidation(False, reason=MoveReason.INVALID_MOVE)
            return MoveValidation(True, MoveReason.OK)
        return MoveValidation(False, is_valid_move.reason)
    def jump_request(self, pos):
        if not self.game_active:
            return MoveValidation(False, reason=MoveReason.GAME_OVER)

        if self.board.is_cell_empty(pos):
            return MoveValidation(False, reason=MoveReason.EMPTY_SOURCE)
        piece = self.board.get_piece_at(pos)
        if piece.state.is_resting():
            return MoveValidation(False, reason=MoveReason.PIECE_RESTING)
        if not self.rta.add_jump(piece, pos):
            return MoveValidation(False, reason=MoveReason.INVALID_JUMP)
        return MoveValidation(True, MoveReason.OK)

    def piece_color_at(self, pos: Position) -> Optional[Color]:
        """The color of the piece occupying `pos`, or None if empty - lets
        callers (e.g. the server's ownership check) ask this without
        reaching into the board directly."""
        piece = self.board.get_piece_at(pos)
        return None if piece == EMPTY_CELL else piece.color

    def finish_game(self):
        self.game_active = False

    def wait(self, ms):
        king_captured = self.rta.advance_time(ms)
        if king_captured:
            self.finish_game()

    def get_snapshot(self) -> GameSnapshot:
        return GameSnapshot(self.board, self.rta, self.scores)