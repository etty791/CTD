"""
End-to-end tests for KungFu Chess.

Coordinate system (from controller.py)
---------------------------------------
  handle_click(game, x, y)
      col = x // 100
      row = y // 100
  So:  click <col_pixels> <row_pixels>

Board layout: row 0 is the top row.
White pieces move upward (forward = -1).
White pawn start row = board.rows - 2.
"""
import sys
import os
import pytest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import input.controller as controller_module
from textTester.script_runner import run_script


def run(script: str, capsys=None):
    """Reset controller state, run a text script, return stdout."""
    controller_module.selected_piece_pos = None
    with patch("sys.stdin", StringIO(script)):
        run_script()
    if capsys:
        return capsys.readouterr().out
    return ""


# click helpers: click(col, row) → "click <col*100> <row*100>"
def click(col, row):
    return f"click {col * 100} {row * 100}\n"


# ---------------------------------------------------------------------------
# 1. Basic move
# ---------------------------------------------------------------------------
class TestBasicMove:
    def test_rook_moves_and_captures_after_wait(self, capsys):
        # wR at row=0,col=0  bK at row=0,col=3  distance=3 → 3000 ms
        script = (
            "Board:\n"
            "wR . . bK\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(3, 0)   # target bK (enemy)
            + "wait 3000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "wR" in out
        assert "bK" not in out

    def test_piece_not_moved_before_wait(self, capsys):
        script = (
            "Board:\n"
            "wR . . bK\n"
            "Commands:\n"
            + click(0, 0)
            + click(3, 0)
            + "print board\n"   # before wait
        )
        out = run(script, capsys)
        assert "wR" in out
        assert "bK" in out


# ---------------------------------------------------------------------------
# 2. King capture ends the game
# ---------------------------------------------------------------------------
class TestKingCapture:
    def test_game_over_after_king_captured(self, capsys):
        # wQ at (row=0,col=0), bK at (row=0,col=2), distance=2 → 2000 ms
        script = (
            "Board:\n"
            "wQ . bK\n"
            "Commands:\n"
            + click(0, 0)
            + click(2, 0)
            + "wait 2000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" not in out

    def test_clicks_ignored_after_game_over(self, capsys):
        script = (
            "Board:\n"
            "wQ . bK\n"
            "Commands:\n"
            + click(0, 0)
            + click(2, 0)
            + "wait 2000\n"
            + click(0, 0)   # game over – should be no-op
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" not in out


# ---------------------------------------------------------------------------
# 3. Pawn promotion
# ---------------------------------------------------------------------------
class TestPawnPromotion:
    def test_white_pawn_promotes_to_queen(self, capsys):
        # 3-row board; white pawn start row = rows-2 = 1
        # wP at (row=1,col=0) captures diagonally to (row=0,col=1) where bK sits
        script = (
            "Board:\n"
            ". bK .\n"
            "wP . .\n"
            ". . .\n"
            "Commands:\n"
            + click(0, 1)   # select wP at col=0,row=1
            + click(1, 0)   # capture bK at col=1,row=0 (diagonal)
            + "wait 1000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "wQ" in out
        assert "bK" not in out


# ---------------------------------------------------------------------------
# 4. Collision: two pieces arrive at same cell simultaneously
# ---------------------------------------------------------------------------
class TestCollision:
    def test_collision_clears_target_cell(self, capsys):
        # wR at (row=0,col=0) and bR at (row=2,col=0) both target (row=1,col=0)
        # distance=1 each → arrive at 1000 ms
        script = (
            "Board:\n"
            "wR .\n"
            ". .\n"
            "bR .\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(0, 1)   # target (col=0,row=1)
            + click(0, 2)   # select bR
            + click(0, 1)   # target (col=0,row=1)
            + "wait 1000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        lines = [l for l in out.strip().splitlines() if l.strip()]
        middle_row = lines[1].split()
        assert middle_row[0] == "."


# ---------------------------------------------------------------------------
# 5. Invalid moves are rejected
# ---------------------------------------------------------------------------
class TestInvalidMove:
    def test_rook_cannot_move_diagonally(self, capsys):
        # wR at (row=0,col=0), bK at (row=1,col=1) – diagonal is illegal for rook
        script = (
            "Board:\n"
            "wR . .\n"
            ". bK .\n"
            ". . .\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(1, 1)   # target (col=1,row=1) – illegal
            + "wait 2000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" in out

    def test_blocked_rook_cannot_jump(self, capsys):
        # wR at (row=0,col=0), wP blocking at (row=0,col=1), bK at (row=0,col=2)
        script = (
            "Board:\n"
            "wR wP bK\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(2, 0)   # target bK – path blocked
            + "wait 3000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" in out


# ---------------------------------------------------------------------------
# 6. Click-select mechanics
# ---------------------------------------------------------------------------
class TestClickSelect:
    def test_click_empty_cell_does_not_select(self, capsys):
        # First click on empty cell → nothing selected; second click selects wR;
        # third click on bK → move requested
        script = (
            "Board:\n"
            ". wR bK\n"
            "Commands:\n"
            + click(0, 0)   # empty – nothing selected
            + click(1, 0)   # select wR
            + click(2, 0)   # target bK, distance=1 → 1000 ms
            + "wait 1000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" not in out

    def test_reselect_friendly_piece(self, capsys):
        # Click wR, then click wQ (friendly) → reselects wQ; then capture bK
        script = (
            "Board:\n"
            "wR wQ bK\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(1, 0)   # reselect wQ (friendly)
            + click(2, 0)   # wQ captures bK, distance=1 → 1000 ms
            + "wait 1000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        assert "bK" not in out
        assert "wQ" in out


# ---------------------------------------------------------------------------
# 7. Piece cannot be re-queued while already moving
# ---------------------------------------------------------------------------
class TestSequentialMoves:
    def test_piece_cannot_move_while_already_moving(self, capsys):
        # wR queued toward bK; a second move from same origin must be rejected
        # Board: wR . bK .  (1 row, 4 cols)
        # First move: wR(col=0) → bK(col=2), distance=2 → 2000 ms
        # Second attempt: try to move wR again before it arrives
        script = (
            "Board:\n"
            "wR . bK .\n"
            "Commands:\n"
            + click(0, 0)   # select wR
            + click(2, 0)   # queue move to bK
            + click(0, 0)   # try to select wR again (still at origin on board)
            + click(3, 0)   # attempt second move – should be rejected by RTA
            + "wait 2000\n"
            + "print board\n"
        )
        out = run(script, capsys)
        # bK captured by first move; wR ends at col=2
        assert "bK" not in out
