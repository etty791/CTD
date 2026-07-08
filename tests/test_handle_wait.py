import pytest
from helpers import make_board
from game import KungFuChessGame


def make_game(pieces: dict) -> KungFuChessGame:
    """pieces: {(row,col): 'piece_str'}"""
    grid = [['.' for _ in range(8)] for _ in range(8)]
    for (r, c), p in pieces.items():
        grid[r][c] = p
    return KungFuChessGame(make_board(grid))


def add_pending(game, piece, origin, target, arrival_time):
    game.pending_moves.append({
        'piece': piece,
        'origin': origin,
        'target': target,
        'arrival_time': arrival_time,
    })


# ── clock ──────────────────────────────────────────────────────────────────────

def test_clock_advances():
    game = make_game({})
    game.handle_wait(500)
    assert game.clock == 500


def test_clock_accumulates_across_calls():
    game = make_game({})
    game.handle_wait(300)
    game.handle_wait(700)
    assert game.clock == 1000


def test_clock_zero_wait_does_not_change():
    game = make_game({})
    game.handle_wait(0)
    assert game.clock == 0


# ── normal arrival ─────────────────────────────────────────────────────────────

def test_piece_placed_at_target_on_arrival():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.board.get_piece_at((0, 5)) == 'wR'


def test_origin_cleared_on_arrival():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.board.is_cell_empty((0, 0))


def test_move_removed_from_pending_on_arrival():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.pending_moves == []


def test_piece_not_placed_before_arrival():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(2999)
    assert game.board.is_cell_empty((0, 5))
    assert len(game.pending_moves) == 1


def test_piece_placed_exactly_at_arrival_time():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 1000)
    game.handle_wait(1000)
    assert game.board.get_piece_at((0, 5)) == 'wR'


# ── origin replaced (movement conflict) ───────────────────────────────────────

def test_move_cancelled_if_origin_piece_changed():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.board.set_piece_at((0, 0), 'bQ')   # origin overwritten
    game.handle_wait(3000)
    assert game.board.is_cell_empty((0, 5))
    assert game.board.get_piece_at((0, 0)) == 'bQ'


def test_move_cancelled_if_origin_emptied():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.board.set_piece_at((0, 0), '.')    # piece removed externally
    game.handle_wait(3000)
    assert game.board.is_cell_empty((0, 5))


def test_cancelled_conflict_move_removed_from_pending():
    game = make_game({(0, 0): 'wR'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.board.set_piece_at((0, 0), 'bQ')
    game.handle_wait(3000)
    assert game.pending_moves == []


# ── friendly piece at target ───────────────────────────────────────────────────

def test_move_cancelled_if_friendly_at_target():
    game = make_game({(0, 0): 'wR', (0, 5): 'wB'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.board.get_piece_at((0, 5)) == 'wB'   # friendly untouched
    assert game.board.get_piece_at((0, 0)) == 'wR'   # rook stays


def test_friendly_block_move_removed_from_pending():
    game = make_game({(0, 0): 'wR', (0, 5): 'wB'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.pending_moves == []


# ── enemy capture ──────────────────────────────────────────────────────────────

def test_enemy_at_target_is_captured():
    game = make_game({(0, 0): 'wR', (0, 5): 'bP'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.board.get_piece_at((0, 5)) == 'wR'


# ── path blocked for sliders (NON_JUMPERS) ────────────────────────────────────

def test_slider_cancelled_if_path_blocked_at_arrival():
    game = make_game({(0, 0): 'wR', (0, 3): 'bP'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.board.is_cell_empty((0, 5))
    assert game.board.get_piece_at((0, 0)) == 'wR'


def test_slider_cancelled_removed_from_pending():
    game = make_game({(0, 0): 'wR', (0, 3): 'bP'})
    add_pending(game, 'wR', (0, 0), (0, 5), 3000)
    game.handle_wait(3000)
    assert game.pending_moves == []


def test_knight_not_blocked_by_pieces_in_path():
    # Knights are jumpers — path check does NOT apply
    game = make_game({(0, 0): 'wN', (0, 1): 'bP', (1, 0): 'bP'})
    add_pending(game, 'wN', (0, 0), (1, 2), 2000)
    game.handle_wait(2000)
    assert game.board.get_piece_at((1, 2)) == 'wN'


# ── two-piece collision at same target ────────────────────────────────────────

def test_two_pieces_collide_both_removed():
    game = make_game({(0, 0): 'wR', (7, 5): 'bR'})
    add_pending(game, 'wR', (0, 0), (4, 0), 4000)
    add_pending(game, 'bR', (7, 5), (4, 0), 4000)
    game.handle_wait(4000)
    assert game.board.is_cell_empty((4, 0))


def test_two_pieces_collide_origins_cleared():
    game = make_game({(0, 0): 'wR', (7, 5): 'bR'})
    add_pending(game, 'wR', (0, 0), (4, 0), 4000)
    add_pending(game, 'bR', (7, 5), (4, 0), 4000)
    game.handle_wait(4000)
    assert game.board.is_cell_empty((0, 0))
    assert game.board.is_cell_empty((7, 5))


def test_two_pieces_collide_removed_from_pending():
    game = make_game({(0, 0): 'wR', (7, 5): 'bR'})
    add_pending(game, 'wR', (0, 0), (4, 0), 4000)
    add_pending(game, 'bR', (7, 5), (4, 0), 4000)
    game.handle_wait(4000)
    assert game.pending_moves == []


def test_collision_does_not_affect_other_moves():
    game = make_game({(0, 0): 'wR', (7, 5): 'bR', (3, 3): 'wB'})
    add_pending(game, 'wR', (0, 0), (4, 0), 4000)
    add_pending(game, 'bR', (7, 5), (4, 0), 4000)
    add_pending(game, 'wB', (3, 3), (5, 5), 4000)
    game.handle_wait(4000)
    assert game.board.get_piece_at((5, 5)) == 'wB'


# ── multiple independent moves ────────────────────────────────────────────────

def test_multiple_moves_all_arrive_same_tick():
    game = make_game({(0, 0): 'wR', (7, 7): 'bR'})
    add_pending(game, 'wR', (0, 0), (0, 3), 3000)
    add_pending(game, 'bR', (7, 7), (7, 4), 3000)
    game.handle_wait(3000)
    assert game.board.get_piece_at((0, 3)) == 'wR'
    assert game.board.get_piece_at((7, 4)) == 'bR'


def test_only_arrived_moves_processed():
    game = make_game({(0, 0): 'wR', (7, 7): 'bR'})
    add_pending(game, 'wR', (0, 0), (0, 3), 2000)
    add_pending(game, 'bR', (7, 7), (7, 4), 5000)
    game.handle_wait(2000)
    assert game.board.get_piece_at((0, 3)) == 'wR'
    assert game.board.is_cell_empty((7, 4))
    assert len(game.pending_moves) == 1


def test_no_pending_moves_no_error():
    game = make_game({})
    game.handle_wait(9999)   # should not raise
    assert game.pending_moves == []
