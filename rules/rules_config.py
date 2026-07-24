from enum import StrEnum


class MoveReason(StrEnum):
    """Canonical vocabulary for MoveValidation.reason values.

    StrEnum members compare equal to their string value and str()/format()
    yield the bare value, so existing `reason == "ok"` checks and
    `"...".format(reason=validation.reason)` calls keep working unchanged.
    """

    OK = "ok"
    EMPTY_SOURCE = "empty_source"
    ILLEGAL_PIECE_MOVE = "illegal_piece_move"
    GAME_OVER = "game_over"
    PIECE_RESTING = "piece_resting"
    INVALID_MOVE = "invalid_move"
    INVALID_JUMP = "invalid_jump"
