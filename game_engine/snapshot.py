from typing import List
from model.position import Position
from model.piece import State
from model.game_snapshot import PieceDTO


class GameSnapshot:
    """Builds the view-facing PieceDTO list from the board and the
    arbiter's in-flight moves. Lives in game_engine (not model) because it
    needs real_time knowledge of pending moves, which model must not
    depend on."""

    def __init__(self, board, arbiter):
        self._board = board
        self._arbiter = arbiter

    def get_all_pieces(self) -> List[PieceDTO]:
        moves_by_piece_id = {move.piece.id: move for move in self._arbiter.pending_moves}
        clock = self._arbiter.clock

        pieces = []
        for row in range(self._board.rows):
            for col in range(self._board.cols):
                pos = Position(row, col)
                if not self._board.is_cell_empty(pos):
                    piece = self._board.get_piece_at(pos)
                    if piece.state != State.captured:
                        origin, target, progress = self._motion(piece, pos, moves_by_piece_id, clock)
                        pieces.append(PieceDTO(
                            id=piece.id,
                            position=pos,
                            type=piece.type,
                            color=piece.color,
                            state=piece.state,
                            origin=origin,
                            target=target,
                            progress=progress,
                        ))

        return pieces

    def _motion(self, piece, pos, moves_by_piece_id, clock):
        move = moves_by_piece_id.get(piece.id)
        if move is None:
            return pos, pos, 0.0

        duration = move.arrival_time - move.start_time
        progress = 1.0 if duration <= 0 else (clock - move.start_time) / duration
        progress = min(1.0, max(0.0, progress))
        return move.origin, move.target, progress
