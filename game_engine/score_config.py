from model.piece import PieceType

# Standard chess piece values. KING is intentionally absent: a king capture
# ends the game via GameEnded, not scoring - see ScoreTracker.
PIECE_VALUES: dict[PieceType, int] = {
    PieceType.PAWN: 1,
    PieceType.KNIGHT: 3,
    PieceType.BISHOP: 3,
    PieceType.ROOK: 5,
    PieceType.QUEEN: 9,
}
