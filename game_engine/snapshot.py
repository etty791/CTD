from dataclasses import dataclass
from typing import Dict, List, Optional
from model.position import Position
from model.piece import Color, State
from model.game_snapshot import PieceDTO


@dataclass(frozen=True)
class _Motion:
    """Where a piece is travelling right now, in both the sampled form the
    local view renders from (`progress`) and the absolute form the wire
    carries (`start_ms`/`arrival_ms`). Both None when the piece is at rest."""

    origin: Position
    target: Position
    progress: float
    start_ms: Optional[int]
    arrival_ms: Optional[int]


class GameSnapshot:
    """Builds the view-facing PieceDTO list from the board and the
    arbiter's in-flight moves. Lives in game_engine (not model) because it
    needs real_time knowledge of pending moves, which model must not
    depend on."""

    def __init__(self, board, arbiter, score_tracker):
        self._board = board
        self._arbiter = arbiter
        self._score_tracker = score_tracker

    def get_all_pieces(self) -> List[PieceDTO]:
        moves_by_piece_id = {move.piece.id: move for move in self._arbiter.pending_moves}
        clock = self._arbiter.clock

        pieces = []
        seen_piece_ids = set()
        for row in range(self._board.rows):
            for col in range(self._board.cols):
                pos = Position(row, col)
                if not self._board.is_cell_empty(pos):
                    piece = self._board.get_piece_at(pos)
                    if piece.state != State.captured:
                        motion = self._motion(piece, pos, moves_by_piece_id, clock)
                        pieces.append(PieceDTO(
                            id=piece.id,
                            position=pos,
                            type=piece.type,
                            color=piece.color,
                            state=piece.state,
                            origin=motion.origin,
                            target=motion.target,
                            progress=motion.progress,
                            move_start_ms=motion.start_ms,
                            move_arrival_ms=motion.arrival_ms,
                        ))
                        seen_piece_ids.add(piece.id)

        # A mid-flight piece vacates its origin cell partway through its
        # move (see RealTimeArbiter._vacate_departed_origins), so the board
        # scan above no longer finds it - without this it would disappear
        # from the snapshot until it lands. Report it at move.origin, which
        # is exactly the position the board scan would have reported for
        # it before it vacated.
        for move in self._arbiter.pending_moves:
            piece = move.piece
            if piece.id in seen_piece_ids or piece.state == State.captured:
                continue
            motion = self._motion(piece, move.origin, moves_by_piece_id, clock)
            pieces.append(PieceDTO(
                id=piece.id,
                position=move.origin,
                type=piece.type,
                color=piece.color,
                state=piece.state,
                origin=motion.origin,
                target=motion.target,
                progress=motion.progress,
                move_start_ms=motion.start_ms,
                move_arrival_ms=motion.arrival_ms,
            ))

        return pieces

    def get_scores(self) -> Dict[Color, int]:
        return {color: self._score_tracker.get_score(color) for color in Color}

    def get_clock_ms(self) -> int:
        """The arbiter clock this snapshot was taken at - the timebase every
        PieceDTO's move_start_ms/move_arrival_ms is expressed in."""
        return self._arbiter.clock

    def _motion(self, piece, pos, moves_by_piece_id, clock) -> _Motion:
        move = moves_by_piece_id.get(piece.id)
        if move is None:
            return _Motion(pos, pos, 0.0, None, None)

        duration = move.arrival_time - move.start_time
        progress = 1.0 if duration <= 0 else (clock - move.start_time) / duration
        progress = min(1.0, max(0.0, progress))
        return _Motion(
            move.origin, move.target, progress, move.start_time, move.arrival_time
        )
