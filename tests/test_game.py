import pytest
from helpers import make_board
from game import KungFuChessGame


# --- get_piece_color / get_piece_type ---

def test_get_piece_color_white(empty_game):
    assert empty_game.get_piece_color('wR') == 'w'


def test_get_piece_color_black(empty_game):
    assert empty_game.get_piece_color('bK') == 'b'


def test_get_piece_color_empty(empty_game):
    assert empty_game.get_piece_color('.') is None


def test_get_piece_type(empty_game):
    assert empty_game.get_piece_type('wQ') == 'Q'


def test_get_piece_type_empty(empty_game):
    assert empty_game.get_piece_type('.') is None


# --- transfer_pixels_to_data ---

def test_transfer_pixels_to_data(empty_game):
    assert empty_game.transfer_pixels_to_data(0) == 0
    assert empty_game.transfer_pixels_to_data(100) == 1
    assert empty_game.transfer_pixels_to_data(350) == 3


# --- is_path_clear ---

def test_is_path_clear_horizontal(empty_game):
    assert empty_game.is_path_clear((4, 0), (4, 7)) is True


def test_is_path_clear_blocked(empty_game):
    empty_game.board.set_piece_at((4, 3), 'bP')
    assert empty_game.is_path_clear((4, 0), (4, 7)) is False


def test_is_path_clear_diagonal(empty_game):
    assert empty_game.is_path_clear((0, 0), (4, 4)) is True


# --- handle_wait ---

def test_handle_wait_advances_clock(empty_game):
    empty_game.handle_wait(500)
    assert empty_game.clock == 500


def test_handle_wait_accumulates(empty_game):
    empty_game.handle_wait(300)
    empty_game.handle_wait(700)
    assert empty_game.clock == 1000


# --- handle_click: selection ---

def test_click_selects_empty_cell(empty_game):
    empty_game.handle_click(0, 0)  # cell (0,0) is empty
    assert empty_game.selected_piece_coords == None


def test_click_on_piece_does_not_select(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.handle_click(0, 0)
    assert empty_game.selected_piece_coords == (0, 0)


def test_click_switches_selection_to_same_color():
    grid = [['.' for _ in range(8)] for _ in range(8)]
    grid[0][0] = 'wR'
    grid[1][0] = 'wB'
    game = KungFuChessGame(make_board(grid))
    game.handle_click(200, 0)  # row=2, col=0 — empty
    assert game.selected_piece_coords ==None


# --- move ---

def test_move_rook_valid():
    grid = [['.' for _ in range(8)] for _ in range(8)]
    grid[4][0] = 'wR'
    game = KungFuChessGame(make_board(grid))
    result = game.move('wR', (4, 0), (4, 5))
    assert result is True
    # piece is still at origin until handle_wait processes the move
    assert game.board.get_piece_at((4, 0)) == 'wR'
    assert game.board.is_cell_empty((4, 5))
    assert len(game.pending_moves) == 1


def test_move_same_origin_target(empty_game):
    empty_game.board.set_piece_at((3, 3), 'wQ')
    assert empty_game.move('wQ', (3, 3), (3, 3)) is False


def test_move_queen_horizontal_valid(empty_game):
    # Queen can move horizontally — this is a valid move
    empty_game.board.set_piece_at((3, 3), 'wQ')
    assert empty_game.move('wQ', (3, 3), (3, 1)) is True


def test_move_knight_valid():
    grid = [['.' for _ in range(8)] for _ in range(8)]
    grid[4][4] = 'wN'
    game = KungFuChessGame(make_board(grid))
    result = game.move('wN', (4, 4), (2, 5))
    assert result is True
    assert len(game.pending_moves) == 1
    game.handle_wait(2000)
    assert game.board.get_piece_at((2, 5)) == 'wN'


# --- try_move ---

def test_try_move_adds_to_pending(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    result = empty_game.try_move('wR', (0, 0), (0, 5))
    assert result is True
    assert len(empty_game.pending_moves) == 1


def test_try_move_correct_arrival_time(empty_game):
    # distance=5 cols → arrival = 0 + 5*1000 = 5000
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 5))
    assert empty_game.pending_moves[0]['arrival_time'] == 5000


def test_try_move_diagonal_arrival_time(empty_game):
    # distance = max(3,3) = 3 → arrival = 3000
    empty_game.board.set_piece_at((0, 0), 'wB')
    empty_game.try_move('wB', (0, 0), (3, 3))
    assert empty_game.pending_moves[0]['arrival_time'] == 3000


def test_try_move_blocks_duplicate_origin(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 5))
    result = empty_game.try_move('wR', (0, 0), (0, 3))
    assert result is False
    assert len(empty_game.pending_moves) == 1


def test_try_move_different_origins_both_allowed(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((1, 0), 'bR')
    empty_game.try_move('wR', (0, 0), (0, 5))
    result = empty_game.try_move('bR', (1, 0), (1, 5))
    assert result is True
    assert len(empty_game.pending_moves) == 2


def test_try_move_stores_correct_fields(empty_game):
    empty_game.board.set_piece_at((2, 2), 'wQ')
    empty_game.try_move('wQ', (2, 2), (2, 6))
    move = empty_game.pending_moves[0]
    assert move['piece'] == 'wQ'
    assert move['origin'] == (2, 2)
    assert move['target'] == (2, 6)


# --- handle_wait ---

def test_handle_wait_places_piece_on_arrival(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 3)) == 'wR'
    assert empty_game.board.is_cell_empty((0, 0))


def test_handle_wait_does_not_place_before_arrival(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.handle_wait(2000)
    assert empty_game.board.is_cell_empty((0, 3))
    assert len(empty_game.pending_moves) == 1


def test_handle_wait_removes_from_pending_after_arrival(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))
    empty_game.handle_wait(3000)
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_multiple_moves_arrive_in_order(empty_game):
    # wR distance=2 → arrival=2000, bR distance=5 → arrival=5000
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((1, 0), 'bR')
    empty_game.try_move('wR', (0, 0), (0, 2))  # arrival=2000
    empty_game.try_move('bR', (1, 0), (1, 5))  # arrival=5000
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 2)) == 'wR'
    assert empty_game.board.is_cell_empty((1, 5))
    assert len(empty_game.pending_moves) == 1


def test_handle_wait_origin_replaced_does_not_clear(empty_game):
    # If origin was overwritten by another piece, don't clear it
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))
    empty_game.board.set_piece_at((0, 0), 'bQ')  # origin replaced
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 0)) == 'bQ'


def test_handle_wait_overwrites_target(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((0, 3), 'bP')  # enemy at target
    empty_game.try_move('wR', (0, 0), (0, 3))
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 3)) == 'wR'


# --- handle_wait: edge cases ---

def test_handle_wait_exact_arrival_time_triggers(empty_game):
    # arrival_time == clock should trigger the move
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 1))  # arrival=1000
    empty_game.handle_wait(1000)
    assert empty_game.board.get_piece_at((0, 1)) == 'wR'


def test_handle_wait_piece_not_moved_one_tick_before_arrival(empty_game):
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.handle_wait(2999)
    assert empty_game.board.get_piece_at((0, 0)) == 'wR'
    assert empty_game.board.is_cell_empty((0, 3))


def test_handle_wait_no_pending_moves_noop(empty_game):
    empty_game.handle_wait(9999)
    assert empty_game.clock == 9999
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_cumulative_clock_triggers_move(empty_game):
    # Move arrives after three separate handle_wait calls that sum to arrival_time
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.handle_wait(1000)
    empty_game.handle_wait(1000)
    empty_game.handle_wait(1000)
    assert empty_game.board.get_piece_at((0, 3)) == 'wR'
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_two_pieces_collide_same_target_both_cleared(empty_game):
    # Two pieces arrive at the same target simultaneously → target empty, both removed
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((0, 6), 'bR')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.try_move('bR', (0, 6), (0, 3))  # arrival=3000
    empty_game.handle_wait(3000)
    assert empty_game.board.is_cell_empty((0, 3))
    assert empty_game.board.is_cell_empty((0, 0))
    assert empty_game.board.is_cell_empty((0, 6))
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_friendly_piece_at_target_cancels_move(empty_game):
    # Friendly piece occupies target → move cancelled, neither piece moved
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((0, 3), 'wB')
    empty_game.try_move('wR', (0, 0), (0, 3))
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 3)) == 'wB'
    assert empty_game.board.get_piece_at((0, 0)) == 'wR'
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_slider_blocked_mid_path_cancels(empty_game):
    # Rook (slider) has a blocker mid-path → move cancelled at arrival
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((0, 2), 'bP')
    empty_game.try_move('wR', (0, 0), (0, 5))
    empty_game.handle_wait(5000)
    assert empty_game.board.get_piece_at((0, 0)) == 'wR'
    assert empty_game.board.is_cell_empty((0, 5))
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_origin_overwritten_move_cancelled(empty_game):
    # Origin piece replaced before arrival → move is discarded, target untouched
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.try_move('wR', (0, 0), (0, 3))
    empty_game.board.set_piece_at((0, 0), 'bQ')
    empty_game.handle_wait(3000)
    assert empty_game.board.is_cell_empty((0, 3))
    assert empty_game.board.get_piece_at((0, 0)) == 'bQ'


def test_handle_wait_only_arrived_moves_processed(empty_game):
    # Only the move whose arrival_time <= clock is processed
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((1, 0), 'bR')
    empty_game.try_move('wR', (0, 0), (0, 1))  # arrival=1000
    empty_game.try_move('bR', (1, 0), (1, 7))  # arrival=7000
    empty_game.handle_wait(1000)
    assert empty_game.board.get_piece_at((0, 1)) == 'wR'
    assert empty_game.board.get_piece_at((1, 0)) == 'bR'
    assert len(empty_game.pending_moves) == 1


def test_handle_wait_knight_not_blocked_by_mid_path_piece(empty_game):
    # Knights are not in NON_JUMPERS → path check skipped, move succeeds
    empty_game.board.set_piece_at((4, 4), 'wN')
    empty_game.board.set_piece_at((3, 4), 'bP')  # piece in the way — irrelevant for knight
    empty_game.try_move('wN', (4, 4), (2, 5))
    empty_game.handle_wait(2000)
    assert empty_game.board.get_piece_at((2, 5)) == 'wN'


def test_handle_wait_multiple_moves_all_arrive_same_tick(empty_game):
    # Two moves to different targets both arrive at the same clock tick
    empty_game.board.set_piece_at((0, 0), 'wR')
    empty_game.board.set_piece_at((7, 7), 'bB')
    empty_game.try_move('wR', (0, 0), (0, 3))  # arrival=3000
    empty_game.try_move('bB', (7, 7), (4, 4))  # arrival=3000
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((0, 3)) == 'wR'
    assert empty_game.board.get_piece_at((4, 4)) == 'bB'
    assert len(empty_game.pending_moves) == 0


def test_handle_wait_clock_updated_even_with_no_moves(empty_game):
    empty_game.handle_wait(500)
    empty_game.handle_wait(500)
    assert empty_game.clock == 1000


def test_handle_wait_enemy_capture_removes_defender(empty_game):
    # Enemy piece at target is replaced by the moving piece
    empty_game.board.set_piece_at((3, 3), 'wQ')
    empty_game.board.set_piece_at((3, 6), 'bP')
    empty_game.try_move('wQ', (3, 3), (3, 6))  # arrival=3000
    empty_game.handle_wait(3000)
    assert empty_game.board.get_piece_at((3, 6)) == 'wQ'
    assert empty_game.board.is_cell_empty((3, 3))
