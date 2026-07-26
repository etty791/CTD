import pytest
from unittest.mock import MagicMock
from model.piece import Color
from model.position import Position
from input.controller import Controller
from input.board_mapper import BoardMapper

# The mapper is a real BoardMapper rather than a mock: pixel -> cell
# translation is part of the behaviour these tests pin down, and with a
# DEFAULT_BOARD_SIZE x DEFAULT_BOARD_SIZE grid over BOARD_PIXELS square,
# each cell is exactly CELL_PIXELS wide.
BOARD_PIXELS = 800
CELL_PIXELS = 100


def make_piece(color: Color):
    piece = MagicMock()
    piece.color = color
    return piece


def make_game(active=True, within=True, empty=False, piece_color=Color.WHITE):
    game = MagicMock()
    game.game_active = active
    game.board.is_within_boundaries.return_value = within
    game.board.is_cell_empty.return_value = empty
    game.board.get_piece_at.return_value = None if empty else make_piece(piece_color)
    return game


def make_controller(game):
    return Controller(game, BoardMapper(BOARD_PIXELS, BOARD_PIXELS))


# --- game inactive ---

def test_game_inactive_returns_early():
    game = make_game(active=False)
    controller = make_controller(game)
    controller.handle_click(100, 100)
    game.board.is_within_boundaries.assert_not_called()
    game.move_request.assert_not_called()

def test_game_inactive_does_not_change_selection():
    game = make_game(active=False)
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(100, 100)
    assert controller.selected_piece_pos == Position(1, 1)


# --- out of bounds ---

def test_out_of_bounds_clears_selection():
    game = make_game(within=False)
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(100, 100)
    assert controller.selected_piece_pos is None

def test_out_of_bounds_no_move_requested():
    game = make_game(within=False)
    controller = make_controller(game)
    controller.handle_click(100, 100)
    game.move_request.assert_not_called()


# --- click empty cell, nothing selected ---

def test_click_empty_nothing_selected_no_move():
    game = make_game(empty=True)
    controller = make_controller(game)
    controller.handle_click(100, 100)
    game.move_request.assert_not_called()

def test_click_empty_nothing_selected_stays_none():
    game = make_game(empty=True)
    controller = make_controller(game)
    controller.handle_click(100, 100)
    assert controller.selected_piece_pos is None


# --- click empty cell, piece already selected ---

def test_click_empty_with_selection_requests_move():
    game = make_game(empty=True)
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(200, 200)
    game.move_request.assert_called_once_with(Position(1, 1), Position(2, 2))

def test_click_empty_with_selection_clears_selection():
    game = make_game(empty=True)
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(200, 200)
    assert controller.selected_piece_pos is None


# --- first click on a piece (select) ---

def test_first_click_piece_sets_selection():
    game = make_game(empty=False, piece_color=Color.WHITE)
    controller = make_controller(game)
    controller.handle_click(100, 200)
    assert controller.selected_piece_pos == Position(2, 1)

def test_first_click_piece_no_move_requested():
    game = make_game(empty=False, piece_color=Color.WHITE)
    controller = make_controller(game)
    controller.handle_click(100, 200)
    game.move_request.assert_not_called()


# --- second click on same-color piece (re-select) ---

def test_same_color_reselects():
    game = make_game(empty=False, piece_color=Color.WHITE)
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(200, 300)

    assert controller.selected_piece_pos == Position(3, 2)
    game.move_request.assert_not_called()


# --- second click on enemy piece (move) ---

def make_enemy_click_game():
    """The controller reads the clicked square first, then the selected one,
    so the side_effect order is [clicked, selected]."""
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = False
    game.board.get_piece_at.side_effect = [make_piece(Color.BLACK), make_piece(Color.WHITE)]
    return game

def test_enemy_click_triggers_move():
    game = make_enemy_click_game()
    controller = make_controller(game)
    selected = Position(1, 1)
    controller.selected_piece_pos = selected
    controller.handle_click(200, 300)

    game.move_request.assert_called_once_with(selected, Position(3, 2))

def test_enemy_click_clears_selection():
    game = make_enemy_click_game()
    controller = make_controller(game)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(200, 300)

    assert controller.selected_piece_pos is None


# --- right click (jump) ---

def test_jump_on_occupied_cell_requests_jump():
    game = make_game(empty=False)
    controller = make_controller(game)
    controller.handle_jump(100, 200)
    game.jump_request.assert_called_once_with(Position(2, 1))

def test_jump_on_empty_cell_requests_nothing():
    game = make_game(empty=True)
    controller = make_controller(game)
    controller.handle_jump(100, 200)
    game.jump_request.assert_not_called()

def test_jump_out_of_bounds_requests_nothing():
    game = make_game(within=False)
    controller = make_controller(game)
    controller.handle_jump(100, 200)
    game.jump_request.assert_not_called()

def test_jump_ignored_when_game_inactive():
    game = make_game(active=False)
    controller = make_controller(game)
    controller.handle_jump(100, 200)
    game.jump_request.assert_not_called()


# --- pixel-to-cell mapping ---

@pytest.mark.parametrize("x, y, expected", [
    (350, 450, Position(4, 3)),                        # mid-cell
    (CELL_PIXELS, CELL_PIXELS, Position(1, 1)),        # exact cell boundary
    (0, 0, Position(0, 0)),                            # top-left corner
    (CELL_PIXELS - 1, CELL_PIXELS - 1, Position(0, 0)),  # just below the boundary
])
def test_pixel_mapping(x, y, expected):
    game = make_game(empty=False)
    controller = make_controller(game)
    controller.handle_click(x, y)
    assert controller.selected_piece_pos == expected
