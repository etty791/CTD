from abc import ABC, abstractmethod
from typing import Set, Tuple

from model.board import Board
from model.piece import  Color, Piece
from model.position import Position


class PieceRules(ABC):
    """Common interface implemented by every piece's rule class."""

    @abstractmethod
    def legal_destinations(self, board: Board, piece: Piece) -> Set[Position]:
        ...


# ---------------------------------------------------------------------------
# 1. Rook
# ---------------------------------------------------------------------------

class _SlidingRules(PieceRules):
    """Shared "slide until blocked" logic, reused by Rook/Bishop/Queen."""

    directions: Tuple[Tuple[int, int], ...] = ()

    def legal_destinations(self, board: Board, piece: Piece) -> Set[Position]:
        destinations: Set[Position] = set()
        for d_row, d_col in self.directions:
            step = Position(d_row, d_col)
            current = piece.position + step
            while board.is_within_boundaries(current):
                if board.is_friendly(current, piece.color):
                    break
                destinations.add(current)
                if board.is_enemy(current, piece.color):
                    break
                current = current + step
        return destinations


class RookRules(_SlidingRules):
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ---------------------------------------------------------------------------
# 2. Bishop
# ---------------------------------------------------------------------------

class BishopRules(_SlidingRules):
    directions = ((1, 1), (1, -1), (-1, 1), (-1, -1))


# ---------------------------------------------------------------------------
# 3. Queen
# ---------------------------------------------------------------------------

class QueenRules(_SlidingRules):
    directions = RookRules.directions + BishopRules.directions


# ---------------------------------------------------------------------------
# 4. Knight
# ---------------------------------------------------------------------------

class KnightRules(PieceRules):
    OFFSETS = (
        (1, 2), (2, 1), (-1, 2), (-2, 1),
        (1, -2), (2, -1), (-1, -2), (-2, -1),
    )

    def legal_destinations(self, board: Board, piece: Piece) -> Set[Position]:
        destinations: Set[Position] = set()
        for d_row, d_col in self.OFFSETS:
            dest = piece.position + Position(d_row, d_col)
            if board.is_within_boundaries(dest) and not board.is_friendly(dest, piece.color):
                destinations.add(dest)
        return destinations


# ---------------------------------------------------------------------------
# 5. King
# ---------------------------------------------------------------------------

class KingRules(PieceRules):
    OFFSETS = tuple(
        (d_row, d_col)
        for d_row in (-1, 0, 1)
        for d_col in (-1, 0, 1)
        if (d_row, d_col) != (0, 0)
    )

    def legal_destinations(self, board: Board, piece: Piece) -> Set[Position]:
        destinations: Set[Position] = set()
        for d_row, d_col in self.OFFSETS:
            dest = piece.position + Position(d_row, d_col)
            if board.is_within_boundaries(dest) and not board.is_friendly(dest, piece.color):
                destinations.add(dest)
        return destinations


# ---------------------------------------------------------------------------
# 6. Pawn (simplified: no two-step, no en passant, no promotion)
# ---------------------------------------------------------------------------
class PawnRules(PieceRules):
    # Row a pawn starts on, used to allow the two-step opening move.
    

    def legal_destinations(self, board: Board, piece: Piece) -> Set[Position]:
        START_ROW = {Color.WHITE: board.rows - 1, Color.BLACK: 0}
        destinations: Set[Position] = set()
        forward = -1 if piece.color == Color.WHITE else 1

        one_step = piece.position + Position(forward, 0)
        if board.is_within_boundaries(one_step) and board.is_cell_empty(one_step):
            destinations.add(one_step)

            two_step = piece.position + Position(forward * 2, 0)
            if (
                piece.position.x == START_ROW[piece.color]
                and board.is_within_boundaries(two_step)
                and board.is_cell_empty(two_step)
            ):
                destinations.add(two_step)

        for d_col in (-1, 1):
            capture = piece.position + Position(forward, d_col)
            if board.is_within_boundaries(capture) and board.is_enemy(capture, piece.color):
                destinations.add(capture)

        return destinations
