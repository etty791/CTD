EMPTY_CELL = '.'
PIXELS_PER_CELL = 100
DEFAULT_MOVE_DELAY_MS = 1000

VALID_TOKENS = frozenset({
    '.',
    'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'
})

COLOR_WHITE = 'w'
COLOR_BLACK = 'b'
NON_JUMPERS  = {'R', 'B', 'Q', 'P'}