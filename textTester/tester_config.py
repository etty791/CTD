"""Vocabulary for the textTester script DSL (`Board:`/`Commands:` sections),
shared between parser.py and script_runner.py so the token/action/error
literals are defined exactly once."""

from model.piece import Color, PieceType

BOARD_SECTION_HEADER = "Board:"
COMMANDS_SECTION_HEADER = "Commands:"

# The DSL's own empty-cell symbol - distinct from Board's internal `None`
# sentinel, which happens to be a different representation entirely.
EMPTY_TOKEN = "."

ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"
ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"

CMD_CLICK = "click"
CMD_JUMP = "jump"
CMD_WAIT = "wait"
CMD_PRINT = "print"
PRINT_ARG_BOARD = "board"
PRINT_ARG_SCORE = "score"

VALID_ACTIONS = {CMD_CLICK, CMD_JUMP, CMD_WAIT, CMD_PRINT}

# Every "<color><type>" piece token (e.g. "wK", "bP"), plus the empty-cell
# sentinel - derived from the Color/PieceType enums rather than spelled out,
# so a new piece type or color is picked up automatically.
VALID_TOKENS = {EMPTY_TOKEN} | {
    f"{color.value}{piece_type.value}" for color in Color for piece_type in PieceType
}
