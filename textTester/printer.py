from model.piece import Color
from model.position import Position
from textTester.tester_config import EMPTY_TOKEN


def print_board(board):
    for x in range(board.rows):
        row = (board.get_piece_at(Position(x, y)) for y in range(board.cols))
        print(" ".join(EMPTY_TOKEN if cell is None else str(cell) for cell in row))


def print_score(scores):
    print(f"White: {scores[Color.WHITE]}")
    print(f"Black: {scores[Color.BLACK]}")