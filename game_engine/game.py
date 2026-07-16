from model.board import Board
from game_engine.snapshot import GameSnapshot
from rules.rules_engine import MoveValidation, validate_move
from real_time.real_time_arbiter import RealTimeArbiter

class KungFuChessGame:
    def __init__(self, initial_board=None):
        if initial_board is None:
            initial_board = Board.generate_standard_grid()
        self.board = Board(initial_board)
        self.rta=RealTimeArbiter(self.board)
        self.game_active = True   

    def move_request(self, origin, target):
        # if origin == target:
        #     return False
        if not self.game_active:
            return MoveValidation(False, reason="game_over")
        is_valid_move = validate_move(self.board, origin, target) 
        if is_valid_move.is_valid:
            if not self.rta.add_move(self.board.get_piece_at(origin), origin, target):
                return MoveValidation(False, reason="invalid_move")
            return MoveValidation(True, "ok")
        return MoveValidation(False, is_valid_move.reason)
    def jump_request(self, pos):
        if not self.game_active:
            return MoveValidation(False, reason="game_over")
        
        if self.board.is_cell_empty(pos):
            return MoveValidation(False, reason="empty_source")
        piece = self.board.get_piece_at(pos)
        if not self.rta.add_jump(piece, pos):
            return MoveValidation(False, reason="invalid_jump")
        return MoveValidation(True, "ok")

    def finish_game(self):
        self.game_active = False

    def wait(self, ms):
        king_captured = self.rta.advance_time(ms)
        if king_captured:
            self.finish_game()

    def get_snapshot(self) -> GameSnapshot:
        return GameSnapshot(self.board, self.rta)