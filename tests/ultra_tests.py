import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.piece import Piece, Color, PieceType
from model.position import Position
from model.board import Board, EMPTY_CELL
from game_engine.game import KungFuChessGame
from input.board_mapper import transfer_pixels_to_data
from input.controller import handle_click

VALID_TOKENS = {
    '.', 'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'
}

def _parse_board(board_str: str):
    rows = board_str.split('\n')
    grid_tokens = [row.split() for row in rows]
    cols = len(grid_tokens[0])
    for row in grid_tokens:
        if len(row) != cols:
            return None, 'ERROR ROW_WIDTH_MISMATCH'
        for token in row:
            if token not in VALID_TOKENS:
                return None, 'ERROR UNKNOWN_TOKEN'
    grid = []
    piece_id = 1
    for x, row in enumerate(grid_tokens):
        board_row = []
        for y, token in enumerate(row):
            if token == EMPTY_CELL:
                board_row.append(EMPTY_CELL)
            else:
                p = Piece(piece_id, token[0], token[1], Position(x, y))
                piece_id += 1
                board_row.append(p)
        grid.append(board_row)
    return grid, None

def _board_to_str(board: Board) -> str:
    return '\n'.join(' '.join(str(cell) for cell in row) for row in board._grid)

def run_chess_game(board_str: str, commands: list[str]) -> str:
    grid, error = _parse_board(board_str)
    if error:
        return error

    import input.controller as ctrl
    ctrl.selected_piece_pos = None

    game = KungFuChessGame(grid)
    outputs = []

    for cmd in commands:
        parts = cmd.split()
        action = parts[0]
        if action == 'click':
            handle_click(game, int(parts[1]), int(parts[2]))
        elif action == 'wait':
            game.wait(int(parts[1]))
        elif action == 'print' and parts[1] == 'board':
            outputs.append(_board_to_str(game.board))

    return '\n'.join(outputs)

TEST_CASES = [
    # --- Parsing & Validation ---
    (
        "parse_empty_board_3x3",
        ". . .\n. . .\n. . .",
        ["print board"],
        ". . .\n. . .\n. . ."
    ),
    (
        "parse_rectangular_board_3x4",
        "wK . . bK\n. . . .\nwR . . bR",
        ["print board"],
        "wK . . bK\n. . . .\nwR . . bR"
    ),
    (
        "parse_piece_tokens_and_colors",
        "wK . bQ\n. wN .\nbP . wR",
        ["print board"],
        "wK . bQ\n. wN .\nbP . wR"
    ),
    (
        "reject_unknown_token",
        "wK xZ\n. .",
        ["print board"],
        "ERROR UNKNOWN_TOKEN"
    ),
    (
        "reject_row_width_mismatch",
        "wK . .\n. bK",
        ["print board"],
        "ERROR ROW_WIDTH_MISMATCH"
    ),

    # --- Selection & Clicking ---
    (
        "select_piece_by_center_click",
        "wK . .\n. . .\n. . .",
        ["click 50 50", "click 150 150", "wait 1000", "print board"],
        ". . .\n. wK .\n. . ."
    ),
    (
        "click_empty_cell_does_not_select",
        "wK . .\n. . .\n. . .",
        ["click 150 150", "click 250 250", "wait 1000", "print board"],
        "wK . .\n. . .\n. . ."
    ),
    (
        "click_outside_board_is_ignored",
        "wK . .\n. . .\n. . .",
        ["click 350 50", "click -10 50", "print board"],
        "wK . .\n. . .\n. . ."
    ),
    (
        "clicking_another_piece_replaces_selection",
        "wR . wK\n. . .",
        ["click 50 50", "click 250 50", "click 250 150", "wait 1000", "print board"],
        "wR . .\n. . wK"
    ),

    # --- Piece Movement Rules ---
    (
        "king_one_step_valid",
        "wK . .\n. . .\n. . .",
        ["click 50 50", "click 150 150", "wait 1000", "print board"],
        ". . .\n. wK .\n. . ."
    ),
    (
        "king_two_steps_invalid",
        "wK . .\n. . .\n. . .",
        ["click 50 50", "click 250 250", "wait 1000", "print board"],
        "wK . .\n. . .\n. . ."
    ),
    (
        "rook_straight_valid",
        "wR . .",
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        ". . wR"
    ),
    (
        "rook_diagonal_invalid",
        "wR . .\n. . .\n. . .",
        ["click 50 50", "click 150 150", "wait 1000", "print board"],
        "wR . .\n. . .\n. . ."
    ),
    (
        "bishop_diagonal_valid",
        "wB . .\n. . .\n. . .",
        ["click 50 50", "click 250 250", "wait 2000", "print board"],
        ". . .\n. . .\n. . wB"
    ),
    (
        "knight_L_valid",
        "wN . .\n. . .\n. . .",
        ["click 50 50", "click 150 250", "wait 3000", "print board"],
        ". . .\n. . .\n. wN ."
    ),
    (
        "queen_diagonal_valid",
        "wQ . .\n. . .\n. . .",
        ["click 50 50", "click 250 250", "wait 2000", "print board"],
        ". . .\n. . .\n. . wQ"
    ),

    # --- Obstacles & Captures ---
    (
        "rook_blocked_by_own_piece",
        "wR wP .",
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        "wR wP ."
    ),
    (
        "bishop_blocked_by_own_piece",
        "wB . .\n. wP .\n. . .",
        ["click 50 50", "click 250 250", "wait 2000", "print board"],
        "wB . .\n. wP .\n. . ."
    ),
    (
        "knight_jumps_over_blockers",
        "wN wP .\nwP . .\n. . .",
        ["click 50 50", "click 150 250", "wait 3000", "print board"],
        ". wP .\nwP . .\n. wN ."
    ),
    (
        "cannot_capture_own_piece",
        "wR . wP",
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        "wR . wP"
    ),
    (
        "rook_captures_enemy_at_destination",
        "wR . bR",
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        ". . wR"
    ),
    (
        "pawn_cannot_capture_forward",
        ". bR .\n. wP .\n. . .",
        ["click 150 150", "click 150 50", "wait 1000", "print board"],
        ". bR .\n. wP .\n. . ."
    ),

    # --- Timing & Concurrency ---
    (
        "one_cell_move_before_arrival_board_unchanged",
        "wR . .",
        ["click 50 50", "click 150 50", "wait 500", "print board"],
        "wR . ."
    ),
    (
        "two_cell_move_before_and_after_arrival",
        "wR . .",
        ["click 50 50", "click 250 50", "wait 1000", "print board", "wait 1000", "print board"],
        # בהתאם למקרה הבדיקה שלך, הפלט הסופי של ההרצה נבדק מול הציפייה:
        "wR . .\n. . wR" 
    ),
    (
        "moving_piece_ignores_redirect",
        "wR . .",
        ["click 50 50", "click 250 50", "wait 1000", "click 50 50", "click 150 50", "wait 1000", "print board"],
        ". . wR"
    ),
    (
        "opposite_colors_do_not_move_concurrently_in_common_route",
        "wR . .\n. . .\nbR . .",
        ["click 50 50", "click 250 50", "click 50 250", "click 250 250", "wait 2000", "print board"],
        ". . wR\n. . .\nbR . ."
    ),
    (
        "no_cooldown_state_in_common_route",
        "wR . .",
        ["click 50 50", "click 150 50", "wait 1000", "print board"],
        ". wR ."
    ),
    (
        "can_move_again_after_arrival_without_cooldown",
        "wR . .",
        ["click 50 50", "click 150 50", "wait 1000", "click 150 50", "click 250 50", "wait 1000", "print board"],
        ". . wR"
    ),
    (
        "piece_is_ready_after_arrival_without_cooldown",
        "wR . .",
        ["click 50 50", "click 150 50", "wait 1000", "click 150 50", "click 250 50", "wait 1000", "print board"],
        ". . wR"
    ),
    (
        "enemy_collision_white_started_first",
        "wR . . bR",
        ["click 50 50", "click 350 50", "click 350 50", "click 50 50", "wait 3000", "print board"],
        ". . . wR"
    ),
    (
        "enemy_collision_black_started_first",
        "wR . . bR",
        ["click 350 50", "click 50 50", "click 50 50", "click 350 50", "wait 3000", "print board"],
        "bR . . ."
    ),
    (
        "cannot_start_move_through_friendly_piece",
        ". . .\nwR wP .\n. . .",
        ["click 50 150", "click 250 150", "wait 2000", "print board"],
        ". . .\nwR wP .\n. . ."
    ),
    (
        "dynamic_block_tactic_not_in_common_route",
        ". . . .\nwQ . . bK\n. . bP .\n. . . .",
        ["click 50 150", "click 350 150", "wait 200", "click 250 250", "click 250 150", "wait 3000", "print board"],
        ". . . .\n. . . wQ\n. . bP .\n. . . ."
    ),
    (
        "knight_cannot_land_on_friendly_piece",
        ". wP .\n. . .\nwN . .",
        ["click 50 250", "click 150 50", "wait 1000", "print board"],
        ". wP .\n. . .\nwN . ."
    ),
    (
        "premove_does_not_execute_in_common_route",
        "wR . .",
        ["click 50 50", "click 150 50", "click 50 50", "click 250 50", "wait 2000", "print board"],
        ". wR ."
    ),

    # --- Game Over & Pawn Mechanics ---
    (
        "king_capture_ends_game",
        "wR . bK",
        ["click 50 50", "click 250 50", "wait 2000", "print board"],
        ". . wR"
    ),
    (
        "no_moves_after_game_over",
        "wR . bK\nbR . .",
        ["click 50 50", "click 250 50", "wait 2000", "click 50 150", "click 150 150", "wait 1000", "print board"],
        ". . wR\nbR . ."
    ),
    (
        "white_pawn_double_from_start_valid",
        ". . .\n. . .\n. . .\n. wP .",
        ["click 150 350", "click 150 150", "wait 2000", "print board"],
        ". . .\n. wP .\n. . .\n. . ."
    ),
    (
        "black_pawn_double_from_start_valid",
        ". bP .\n. . .\n. . .\n. . .",
        ["click 150 50", "click 150 250", "wait 2000", "print board"],
        ". . .\n. . .\n. bP .\n. . ."
    ),
    (
        "white_pawn_double_blocked_invalid",
        ". . .\n. . .\n. bR .\n. wP .",
        ["click 150 350", "click 150 150", "wait 2000", "print board"],
        ". . .\n. . .\n. bR .\n. wP ."
    ),
    (
        "white_pawn_double_from_non_start_invalid",
        ". . .\n. . .\n. wP .\n. . .",
        ["click 150 250", "click 150 50", "wait 2000", "print board"],
        ". . .\n. . .\n. wP .\n. . ."
    ),
    (
        "white_pawn_promotes_to_queen",
        ". . .\n. wP .",
        ["click 150 150", "click 150 50", "wait 1000", "print board"],
        ". wQ .\n. . ."
    ),
    (
        "black_pawn_promotes_to_queen",
        ". bP .\n. . .",
        ["click 150 50", "click 150 150", "wait 1000", "print board"],
        ". . .\n. bQ ."
    ),
    (
        "promoted_queen_moves_diagonal",
        ". . .\n. wP .\n. . .",
        ["click 150 150", "click 150 50", "wait 1000", "click 150 50", "click 250 150", "wait 1000", "print board"],
        ". . .\n. . wQ\n. . ."
    ),

    # --- Jump Mechanics (Airborne) ---
    # pytest.param(
    #     "jump_lands_same_square",
    #     ". . .\n. wK .\n. . .",
    #     ["jump 150 150", "wait 1000", "print board"],
    #     ". . .\n. wK .\n. . .",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # ),
    # pytest.param(
    #     "airborne_piece_captures_arriving_enemy",
    #     ". . .\nwK bR .\n. . .",
    #     ["jump 50 150", "click 150 150", "click 50 150", "wait 1000", "print board"],
    #     ". . .\nwK . .\n. . .",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # ),
    # pytest.param(
    #     "jump_too_late_does_not_save_piece",
    #     ". . .\nwK bR .\n. . .",
    #     ["click 150 150", "click 50 150", "wait 1000", "jump 50 150", "print board"],
    #     ". . .\nbR . .\n. . .",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # ),
    # pytest.param(
    #     "enemy_arrives_after_landing_captures_normally",
    #     ". . . .\nwK . . bR\n. . . .",
    #     ["jump 50 150", "wait 1000", "click 350 150", "click 50 150", "wait 3000", "print board"],
    #     ". . . .\nbR . . .\n. . . .",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # ),
    # pytest.param(
    #     "cannot_jump_while_moving",
    #     "wR . .",
    #     ["click 50 50", "click 250 50", "wait 500", "jump 50 50", "wait 1500", "print board"],
    #     ". . wR",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # ),
    # pytest.param(
    #     "airborne_capture_only_enemy",
    #     ". . .\nwK wR .\n. . .",
    #     ["jump 50 150", "click 150 150", "click 50 150", "wait 1000", "print board"],
    #     ". . .\nwK wR .\n. . .",
    #     marks=pytest.mark.skip(reason="jump not implemented")
    # )
]

@pytest.mark.parametrize("case_name, board, commands, expected_output", TEST_CASES)
def test_chess_cases(case_name, board, commands, expected_output):
    """הרצת מקרי הבדיקה השונים מתוך הרשימה המרוכזת."""
    actual_output = run_chess_game(board, commands)
    
    # ניקוי רווחים מיותרים בשני הצדדים כדי למנוע כישלון בגלל \n בסוף הטקסט
    assert actual_output.strip() == expected_output.strip(), f"Failed on case: {case_name}"