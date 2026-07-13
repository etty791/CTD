
def print_board(board):
    for row in board._grid:
        print(" ".join(str(cell) for cell in row))