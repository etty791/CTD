from dataclasses import dataclass
from typing import Dict

from model.board import Board
from model.piece import PieceType
from model.position import Position

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

def validate_move(
        board: Board, source: Position, destination: Position
    ) -> MoveValidation:
        # if not board.is_in_bounds(source) or not board.is_in_bounds(destination):
        #     return MoveValidation(False, "outside_board")
        
        piece = board.get_piece_at(source)
        if board.is_cell_empty(source):
            return MoveValidation(False, "empty_source")

        # if board.is_friendly(destination, piece.color):
        #     return MoveValidation(False, "friendly_destination")

        rules = _rules[piece.type]
        if destination not in rules.legal_destinations(board, piece):
            return MoveValidation(False, "illegal_piece_move")

        return MoveValidation(True, "ok")
