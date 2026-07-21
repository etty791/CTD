from model.piece import Color


def print_board(board):
    for row in board._grid:
        print(" ".join(str(cell) for cell in row))


def print_score(scores):
    print(f"White: {scores[Color.WHITE]}")
    print(f"Black: {scores[Color.BLACK]}")