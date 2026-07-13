import pytest
from unittest.mock import MagicMock
from model.piece import Color
from model.position import Position
import input.controller as controller


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


@pytest.fixture(autouse=True)
def reset_global():
    controller.selected_piece_pos = None
    yield
    controller.selected_piece_pos = None


# --- game inactive ---

def test_game_inactive_returns_early():
    game = make_game(active=False)
    controller.handle_click(game, 100, 100)
    game.board.is_within_boundaries.assert_not_called()
    game.move_request.assert_not_called()

def test_game_inactive_does_not_change_selection():
    game = make_game(active=False)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 100, 100)
    assert controller.selected_piece_pos == Position(1, 1)


# --- out of bounds ---

def test_out_of_bounds_clears_selection():
    game = make_game(within=False)
    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 100, 100)
    assert controller.selected_piece_pos is None

def test_out_of_bounds_no_move_requested():
    game = make_game(within=False)
    controller.handle_click(game, 100, 100)
    game.move_request.assert_not_called()


# --- click empty cell, nothing selected ---

def test_click_empty_nothing_selected_no_move():
    game = make_game(empty=True)
    controller.handle_click(game, 100, 100)
    game.move_request.assert_not_called()

def test_click_empty_nothing_selected_stays_none():
    game = make_game(empty=True)
    controller.handle_click(game, 100, 100)
    assert controller.selected_piece_pos is None


# --- click empty cell, piece already selected ---

def test_click_empty_with_selection_no_move():
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = True

    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 200, 200)
    game.move_request.assert_called()

def test_click_empty_with_selection_clears_selection():
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = True

    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 200, 200)
    assert controller.selected_piece_pos is None


# --- first click on a piece (select) ---

def test_first_click_piece_sets_selection():
    game = make_game(empty=False, piece_color=Color.WHITE)
    controller.handle_click(game, 100, 200)
    assert controller.selected_piece_pos == Position(2, 1)

def test_first_click_piece_no_move_requested():
    game = make_game(empty=False, piece_color=Color.WHITE)
    controller.handle_click(game, 100, 200)
    game.move_request.assert_not_called()


# --- second click on same-color piece (re-select) ---

def test_same_color_reselects():
    white = make_piece(Color.WHITE)
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = False
    game.board.get_piece_at.return_value = white

    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 200, 300)

    assert controller.selected_piece_pos == Position(3, 2)
    game.move_request.assert_not_called()


# --- second click on enemy piece (move) ---

def test_enemy_click_triggers_move():
    white = make_piece(Color.WHITE)
    black = make_piece(Color.BLACK)
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = False
    game.board.get_piece_at.side_effect = [black, white]

    selected = Position(1, 1)
    controller.selected_piece_pos = selected
    controller.handle_click(game, 200, 300)

    game.move_request.assert_called_once_with(selected, Position(3, 2))

def test_enemy_click_clears_selection():
    white = make_piece(Color.WHITE)
    black = make_piece(Color.BLACK)
    game = MagicMock()
    game.game_active = True
    game.board.is_within_boundaries.return_value = True
    game.board.is_cell_empty.return_value = False
    game.board.get_piece_at.side_effect = [black, white]

    controller.selected_piece_pos = Position(1, 1)
    controller.handle_click(game, 200, 300)

    assert controller.selected_piece_pos is None


# --- pixel-to-cell mapping ---

def test_pixel_mapping_mid_cell():
    game = make_game(empty=False)
    controller.handle_click(game, 350, 450)
    assert controller.selected_piece_pos == Position(4, 3)

def test_pixel_mapping_exact_boundary():
    game = make_game(empty=False)
    controller.handle_click(game, 100, 100)
    assert controller.selected_piece_pos == Position(1, 1)

def test_pixel_mapping_zero():
    game = make_game(empty=False)
    controller.handle_click(game, 0, 0)
    assert controller.selected_piece_pos == Position(0, 0)

def test_pixel_mapping_just_below_boundary():
    game = make_game(empty=False)
    controller.handle_click(game, 99, 99)
    assert controller.selected_piece_pos == Position(0, 0)
