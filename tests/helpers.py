from board import Board


def make_board(grid):
    return Board([row[:] for row in grid])
