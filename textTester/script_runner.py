import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textTester.parser import parse_input
from game_engine.game import KungFuChessGame
from input.controller import Controller
from input.board_mapper import BoardMapper
from view.view_config import DEFAULT_BOARD_SIZE
from textTester.printer import print_board, print_score
from textTester.tester_config import (
    CMD_CLICK,
    CMD_JUMP,
    CMD_PRINT,
    CMD_WAIT,
    ERROR_UNKNOWN_TOKEN,
    VALID_TOKENS,
)

# The text tester has no rendered board image to derive pixel dimensions
# from (unlike the GUI's BoardMapper, sized from the loaded board asset),
# so click/jump coordinates use a fixed pixels-per-square convention.
TEXT_TESTER_SQUARE_SIZE_PX = 100

def run_script():
    board, commands = parse_input(VALID_TOKENS)
    if not board or not commands:
        exit(1)
    game = KungFuChessGame(board)
    board_side_px = DEFAULT_BOARD_SIZE * TEXT_TESTER_SQUARE_SIZE_PX
    board_mapper = BoardMapper(board_side_px, board_side_px)
    controller = Controller(game, board_mapper)
    COMMANDS_TO_ACTIONS = {
        CMD_CLICK: lambda x, y: controller.handle_click(x, y),
        CMD_WAIT: game.wait,
        CMD_PRINT: lambda: print_board(game.board),
        "print_score": lambda: print_score(game.get_snapshot().get_scores()),
        CMD_JUMP: lambda x, y: controller.handle_jump(x, y)
    }

    for cmd in commands:
        action = cmd[0]
        args = cmd[1:]

        if action not in COMMANDS_TO_ACTIONS:
            print(ERROR_UNKNOWN_TOKEN)
            exit(1)

        COMMANDS_TO_ACTIONS[action](*args)



