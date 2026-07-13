import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textTester.parser import parse_input
from game_engine.game import KungFuChessGame
from input.controller import Controller
from textTester.printer import print_board

VALID_TOKENS = {
    '.',
    'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'
}

def run_script():
    board, commands = parse_input(VALID_TOKENS)
    if not board or not commands:
        exit(1)
    game = KungFuChessGame(board)
    controller = Controller(game)
    COMMANDS_TO_ACTIONS = {
        "click": lambda x, y: controller.handle_click(x, y),
        "wait": game.wait,
        "print": lambda: print_board(game.board),
        "jump": lambda x, y: controller.handle_jump(x, y)
    }

    for cmd in commands:
        action = cmd[0]
        args = cmd[1:]

        if action not in COMMANDS_TO_ACTIONS:
            print("ERROR UNKNOWN_TOKEN")
            exit(1)

        COMMANDS_TO_ACTIONS[action](*args)



