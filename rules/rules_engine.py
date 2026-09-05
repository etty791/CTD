from dataclasses import dataclass
from typing import Dict

from model.board import Board
from model.piece import Piece, PieceType
from model.position import Position

from rules.rules_config import MoveReason
from rules.piece_rules import (
    BishopRules,
    KingRules,
    KnightRules,
    PawnRules,
    PieceRules,
    QueenRules,
    RookRules,
)


@dataclass(frozen=True)
class MoveValidation:
    is_valid: bool
    reason: str


_rules: Dict[PieceType, PieceRules] = {
            PieceType.ROOK: RookRules(),
            PieceType.BISHOP: BishopRules(),
            PieceType.QUEEN: QueenRules(),
            PieceType.KNIGHT: KnightRules(),
            PieceType.KING: KingRules(),
            PieceType.PAWN: PawnRules(),
        }

def validate_piece_move(
        board: Board, piece: Piece, destination: Position
    ) -> MoveValidation:
        """Legality of `piece` moving to `destination`, keyed off the piece
        itself rather than its board cell - used to revalidate an in-flight
        move whose origin cell may currently be empty (the piece vacates it
        mid-flight; see real_time/real_time_arbiter.py)."""
        rules = _rules[piece.type]
        if destination not in rules.legal_destinations(board, piece):
            return MoveValidation(False, MoveReason.ILLEGAL_PIECE_MOVE)

        return MoveValidation(True, MoveReason.OK)


def validate_move(
        board: Board, source: Position, destination: Position
    ) -> MoveValidation:
        if not board.is_within_boundaries(source) or not board.is_within_boundaries(destination):
            return MoveValidation(False, MoveReason.OUT_OF_BOUNDS)

        if board.is_cell_empty(source):
            return MoveValidation(False, MoveReason.EMPTY_SOURCE)
        piece = board.get_piece_at(source)

        return validate_piece_move(board, piece, destination)
