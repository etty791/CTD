import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.piece import Piece, Color, PieceType
from model.position import Position
from model.board import Board, EMPTY_CELL
from textTester.parser import (
    parse_input, is_valid_board, create_board,
    create_commands, create_piece_from_string
)
from textTester.printer import print_board, print_score

VALID_TOKENS = {
    '.', 'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'
}

# ─── helpers ────────────────────────────────────────────────────────────────

def make_board_lines(rows):
    return [row.split() for row in rows]

def stdin_with(text):
    return patch("sys.stdin", StringIO(text))


# ═══════════════════════════════════════════════════════════════════════════
# parser.py – create_piece_from_string
# ═══════════════════════════════════════════════════════════════════════════

class TestCreatePieceFromString:
    def test_empty_cell_returns_empty(self):
        assert create_piece_from_string('.', 0, 0, 1) == EMPTY_CELL

    def test_white_king(self):
        p = create_piece_from_string('wK', 0, 0, 1)
        assert p.color == Color.WHITE and p.type == PieceType.KING

    def test_black_pawn(self):
        p = create_piece_from_string('bP', 1, 2, 5)
        assert p.color == Color.BLACK and p.type == PieceType.PAWN
        assert p.position.x == 1 and p.position.y == 2

    def test_id_assigned(self):
        p = create_piece_from_string('wR', 0, 0, 7)
        assert p.id == 7

    def test_all_piece_types(self):
        for ch, pt in [('Q', PieceType.QUEEN), ('R', PieceType.ROOK),
                       ('B', PieceType.BISHOP), ('N', PieceType.KNIGHT)]:
            p = create_piece_from_string(f'w{ch}', 0, 0, 1)
            assert p.type == pt


# ═══════════════════════════════════════════════════════════════════════════
# parser.py – is_valid_board
# ═══════════════════════════════════════════════════════════════════════════

class TestIsValidBoard:
    def test_valid_board(self):
        lines = make_board_lines(['. wK', '. .'])
        assert is_valid_board(lines, VALID_TOKENS) is True

    def test_empty_board_returns_false(self, capsys):
        assert is_valid_board([], VALID_TOKENS) is False
        assert "UNKNOWN_TOKEN" in capsys.readouterr().out

    def test_unknown_token(self, capsys):
        lines = make_board_lines(['XX .'])
        assert is_valid_board(lines, VALID_TOKENS) is False
        assert "UNKNOWN_TOKEN" in capsys.readouterr().out

    def test_row_width_mismatch(self, capsys):
        lines = [['wK', '.'], ['.']]
        assert is_valid_board(lines, VALID_TOKENS) is False
        assert "ROW_WIDTH_MISMATCH" in capsys.readouterr().out

    def test_single_cell_board(self):
        assert is_valid_board([['.']],  VALID_TOKENS) is True

    def test_all_valid_tokens_accepted(self):
        row = list(VALID_TOKENS)
        assert is_valid_board([row], VALID_TOKENS) is True


# ═══════════════════════════════════════════════════════════════════════════
# parser.py – create_board
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateBoard:
    def test_returns_2d_list(self):
        lines = make_board_lines(['. .', '. .'])
        board = create_board(lines, VALID_TOKENS)
        assert len(board) == 2 and len(board[0]) == 2

    def test_pieces_have_sequential_ids(self):
        lines = make_board_lines(['wK wQ'])
        board = create_board(lines, VALID_TOKENS)
        assert board[0][0].id == 1
        assert board[0][1].id == 2

    def test_empty_cells_are_dot(self):
        lines = make_board_lines(['. .'])
        board = create_board(lines, VALID_TOKENS)
        assert board[0][0] == EMPTY_CELL and board[0][1] == EMPTY_CELL

    def test_mixed_row(self):
        lines = make_board_lines(['wK . bK'])
        board = create_board(lines, VALID_TOKENS)
        assert board[0][0].type == PieceType.KING
        assert board[0][1] == EMPTY_CELL
        assert board[0][2].type == PieceType.KING

    def test_invalid_board_exits(self):
        lines = make_board_lines(['XX .'])
        with pytest.raises(SystemExit):
            create_board(lines, VALID_TOKENS)


# ═══════════════════════════════════════════════════════════════════════════
# parser.py – create_commands
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateCommands:
    def test_click_command(self):
        cmds = create_commands(["click 3 4"])
        assert cmds == [("click", 3, 4)]

    def test_wait_command(self):
        cmds = create_commands(["wait 500"])
        assert cmds == [("wait", 500)]

    def test_print_board_command(self):
        cmds = create_commands(["print board"])
        assert cmds == [("print",)]

    def test_print_score_command(self):
        cmds = create_commands(["print score"])
        assert cmds == [("print_score",)]

    def test_multiple_commands(self):
        cmds = create_commands(["click 0 0", "wait 100", "print board"])
        assert len(cmds) == 3

    def test_unknown_action_exits(self, capsys):
        with pytest.raises(SystemExit):
            create_commands(["fly 1 2"])
        assert "UNKNOWN_TOKEN" in capsys.readouterr().out

    def test_empty_list_returns_empty(self):
        assert create_commands([]) == []


# ═══════════════════════════════════════════════════════════════════════════
# parser.py – parse_input
# ═══════════════════════════════════════════════════════════════════════════

class TestParseInput:
    MINIMAL = "Board:\n. .\nCommands:\nprint board\n"

    def test_valid_input_returns_board_and_commands(self):
        with stdin_with(self.MINIMAL):
            board, cmds = parse_input(VALID_TOKENS)
        assert board is not None and cmds is not None

    def test_missing_board_header_returns_none(self, capsys):
        with stdin_with("Commands:\nprint board\n"):
            board, cmds = parse_input(VALID_TOKENS)
        assert board is None and cmds is None
        assert "UNKNOWN_TOKEN" in capsys.readouterr().out

    def test_empty_input_returns_none(self, capsys):
        with stdin_with(""):
            board, cmds = parse_input(VALID_TOKENS)
        assert board is None and cmds is None

    def test_missing_commands_section_returns_none(self, capsys):
        with stdin_with("Board:\n. .\n"):
            board, cmds = parse_input(VALID_TOKENS)
        assert board is None and cmds is None

    def test_blank_lines_ignored(self):
        text = "Board:\n\n. .\n\nCommands:\n\nprint board\n"
        with stdin_with(text):
            board, cmds = parse_input(VALID_TOKENS)
        assert board is not None

    def test_board_dimensions_correct(self):
        text = "Board:\nwK . bK\n. . .\nCommands:\nprint board\n"
        with stdin_with(text):
            board, cmds = parse_input(VALID_TOKENS)
        assert len(board) == 2 and len(board[0]) == 3

    def test_multiple_clicks_parsed(self):
        text = "Board:\n. .\nCommands:\nclick 0 0\nclick 1 1\n"
        with stdin_with(text):
            _, cmds = parse_input(VALID_TOKENS)
        assert len(cmds) == 2

    def test_unknown_token_in_board_returns_none(self, capsys):
        with stdin_with("Board:\nXX .\nCommands:\nprint board\n"):
            with pytest.raises(SystemExit):
                parse_input(VALID_TOKENS)


# ═══════════════════════════════════════════════════════════════════════════
# printer.py – print_board
# ═══════════════════════════════════════════════════════════════════════════

class TestPrintBoard:
    def _make_game_board(self, rows):
        lines = make_board_lines(rows)
        grid = create_board(lines, VALID_TOKENS)
        return Board(grid)

    def test_prints_correct_rows(self, capsys):
        board = self._make_game_board(['. .', '. .'])
        print_board(board)
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 2

    def test_empty_cell_shown_as_dot(self, capsys):
        board = self._make_game_board(['. .'])
        print_board(board)
        assert '. .' in capsys.readouterr().out

    def test_piece_shown_correctly(self, capsys):
        board = self._make_game_board(['wK .'])
        print_board(board)
        assert 'wK .' in capsys.readouterr().out

    def test_single_cell_board(self, capsys):
        board = self._make_game_board(['.'])
        print_board(board)
        assert '.' in capsys.readouterr().out

    def test_row_separator_is_space(self, capsys):
        board = self._make_game_board(['wK bK'])
        print_board(board)
        line = capsys.readouterr().out.strip()
        assert ' ' in line


# ═══════════════════════════════════════════════════════════════════════════
# printer.py – print_score
# ═══════════════════════════════════════════════════════════════════════════

class TestPrintScore:
    def test_prints_both_colors(self, capsys):
        print_score({Color.WHITE: 3, Color.BLACK: 0})
        out = capsys.readouterr().out
        assert "White: 3" in out
        assert "Black: 0" in out


# ═══════════════════════════════════════════════════════════════════════════
# script_runner.py – run_script
# ═══════════════════════════════════════════════════════════════════════════

class TestRunScript:
    SCRIPT = "Board:\n. .\nCommands:\nprint board\n"

    def test_run_script_print(self, capsys):
        from textTester.script_runner import run_script
        with stdin_with(self.SCRIPT):
            run_script()
        assert '. .' in capsys.readouterr().out

    def test_run_script_unknown_command_exits(self, capsys):
        from textTester.script_runner import run_script
        with stdin_with("Board:\n. .\nCommands:\nfly 1 2\n"):
            with pytest.raises(SystemExit):
                run_script()

    def test_run_script_wait_executes(self):
        from textTester.script_runner import run_script
        with stdin_with("Board:\n. .\nCommands:\nwait 0\n"):
            run_script()  # should not raise

    def test_run_script_click_out_of_bounds(self):
        from textTester.script_runner import run_script
        # click far outside board – controller should handle gracefully
        with stdin_with("Board:\n. .\nCommands:\nclick 9999 9999\n"):
            run_script()  # should not raise
