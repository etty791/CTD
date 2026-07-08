from constants import EMPTY_CELL

class Board:
    def __init__(self, initial_grid):
        self._grid = initial_grid
        self.rows = len(initial_grid)
        self.cols = len(initial_grid[0]) if self.rows > 0 else 0

    def get_piece_at(self, coordinates):
        row, col = coordinates
        return self._grid[row][col]

    def set_piece_at(self, coordinates, value):
        row, col = coordinates
        self._grid[row][col] = value

    def is_cell_empty(self, coordinates):
        return self.get_piece_at(coordinates) == EMPTY_CELL

    def is_within_boundaries(self, coordinates):
        row, col = coordinates
        return 0 <= row < self.rows and 0 <= col < self.cols

    def print_board(self):
        for row in self._grid:
            print(" ".join(row))