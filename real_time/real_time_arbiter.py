from model.board import EMPTY_CELL
DEFAULT_MOVE_DELAY_MS=1000
from model.piece import PieceType, State
from rules.rules_engine import validate_move
from model.position import Position

class Move:
    def __init__(self, piece, origin, target, arrival_time, start_time):
        self.piece = piece
        self.origin = origin
        self.target = target
        self.arrival_time = arrival_time
        self.start_time = start_time

def _path_cells(origin, target):
    """Returns all cells along the straight path from origin to target (exclusive of origin, inclusive of target)."""
    cells = []
    dx = 0 if target.x == origin.x else (1 if target.x > origin.x else -1)
    dy = 0 if target.y == origin.y else (1 if target.y > origin.y else -1)
    cur = Position(origin.x + dx, origin.y + dy)
    while cur != target:
        cells.append(cur)
        cur = Position(cur.x + dx, cur.y + dy)
    cells.append(target)
    return cells

class RealTimeArbiter:
    
    def __init__(self,board):
        self.board = board
        self.pending_moves = []    
        self.clock = 0  

    def add_move(self, piece, origin, target):    
        for move in self.pending_moves:
            if move.origin == origin:
                return False

        new_path = set(_path_cells(origin, target))
        for move in self.pending_moves:
            existing_path = set(_path_cells(move.origin, move.target))
            if new_path & existing_path:
                return False

        row_diff = abs(target.x - origin.x)
        col_diff = abs(target.y - origin.y)
        distance = max(row_diff, col_diff)
        
        arrival_time = self.clock + (distance * DEFAULT_MOVE_DELAY_MS)

        move = Move(piece, origin, target, arrival_time, self.clock)
        piece.state = State.moving
        self.pending_moves.append(move)
        return True 

    def advance_time(self, ms):
        king_captured = False
        self.clock += ms
        self._resolve_enemy_path_collisions()
        arrived = self._pop_arrived_moves()
        for target, moves in self._group_by_target(arrived).items():
            if len(moves) > 1:
                self._resolve_collision(moves, target)
            else:
                king_captured = king_captured or self._resolve_single(moves[0])
        return king_captured

    def _resolve_enemy_path_collisions(self):
        """Detect enemy moves whose paths cross; the later-starting piece is captured."""
        to_remove = set()
        moves = self.pending_moves
        for i in range(len(moves)):
            for j in range(i + 1, len(moves)):
                a, b = moves[i], moves[j]
                if a.piece.color == b.piece.color:
                    continue
                if id(a) in to_remove or id(b) in to_remove:
                    continue
                path_a = set(_path_cells(a.origin, a.target))
                path_b = set(_path_cells(b.origin, b.target))
                if not (path_a & path_b):
                    continue
                loser = b if a.start_time <= b.start_time else a
                winner = a if loser is b else b
                to_remove.add(id(loser))
                loser.piece.state = State.captured
                if self.board.get_piece_at(loser.origin) == loser.piece:
                    self.board.set_piece_at(loser.origin, EMPTY_CELL)
                winner.target = loser.origin
        self.pending_moves = [m for m in self.pending_moves if id(m) not in to_remove]

    def _pop_arrived_moves(self):
        arrived = [m for m in self.pending_moves if m.arrival_time <= self.clock]
        arrived.sort(key=lambda m: m.arrival_time)
        for m in arrived:
            self.pending_moves.remove(m)
        return arrived

    def _group_by_target(self, moves):
        groups = {}
        for m in moves:
            groups.setdefault(m.target, []).append(m)
        return groups

    def _resolve_collision(self, moves, target):
        # Sort by arrival time: earliest arrival wins
        moves.sort(key=lambda m: m.arrival_time)
        winner = moves[0]
        losers = moves[1:]
        for m in losers:
            m.piece.state = State.captured
            if self.board.get_piece_at(m.origin) == m.piece:
                self.board.set_piece_at(m.origin, EMPTY_CELL)
        self._apply_move(winner)

    def _resolve_single(self, move):
        if not self._is_still_valid(move):
            return False
        return self._apply_move(move)

    def _is_still_valid(self, move):
        if move.piece.state == State.captured:
            return False
        #check if path still clear
        if not validate_move(self.board, move.origin, move.target).is_valid:
            return False
        target_piece = self.board.get_piece_at(move.target)
        if target_piece != EMPTY_CELL and target_piece.color == move.piece.color:
            return False
        return True

    def _apply_move(self, move):
        target_piece = self.board.get_piece_at(move.target)
        is_game_over = target_piece != EMPTY_CELL and target_piece.kind == PieceType.KING
        self.board.move_piece(move.origin, move.target)
        move.piece.state = State.idle
        return is_game_over
