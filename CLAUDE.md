# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A real-time "Kung Fu Chess" game in Python: there are no turns — any piece may be ordered to move at any time, moves take real time to travel (1000 ms per square, `DEFAULT_MOVE_DELAY_MS`), and pieces collide mid-flight. The game ends when a king is captured.

## Commands

The venv is at `.venv` (Windows). Dependencies: pytest, opencv-python (cv2), numpy — there is no requirements.txt.

```powershell
.venv\Scripts\python.exe -m pytest                          # all tests (pytest.ini sets testpaths=tests)
.venv\Scripts\python.exe -m pytest tests/test_board.py      # one file
.venv\Scripts\python.exe -m pytest tests/test_collisions.py::TestEnemyPathCollision::test_earlier_starter_wins_head_on   # one test
.venv\Scripts\python.exe main.py                            # run the OpenCV GUI
```

The text tester (`textTester/script_runner.py: run_script()`) reads a script from stdin: a `Board:` section of tokens (`.`, `wK`, `bP`, ...) followed by a `Commands:` section (`click x y`, `jump x y`, `wait ms`, `print board`).

## Architecture

Layered, one direction of dependency: `view`/`input`/`textTester` → `game_engine` → `rules` + `real_time` → `model`. Each layer has exactly one job — don't let responsibilities leak across these boundaries:

- **`model/`** — dumb domain state and simple transitions; no rule validation. `Board` wraps an 8x8 grid whose cells hold either a `Piece` or the string sentinel `EMPTY_CELL = '.'` (import it from `model.board`; never compare to a literal). `Piece` carries `id`, `Color`, `PieceType`, `position`, and a `State` enum (`idle`/`moving`/`captured`/`airborne`). `Position(x, y)` is **x = row, y = col**. Board mutation goes through `get_piece_at`/`set_piece_at`/`move_piece`/`is_cell_empty`; `move_piece` also marks captures and applies pawn promotion.
- **`rules/`** — pure, timeless move legality. `rules_engine.validate_move(board, src, dst)` returns a frozen `MoveValidation(is_valid, reason)` dataclass (reasons are strings like `"illegal_piece_move"`, `"empty_source"`, `"game_over"`). It dispatches to per-piece strategy classes in `piece_rules.py` (`_SlidingRules` shared by Rook/Bishop/Queen). No time, no collisions, no mutation here.
- **`real_time/real_time_arbiter.py`** — the heart of the game: timing, pending moves, and path-collision resolution. Owns a millisecond `clock` and a `pending_moves` list. `add_move`/`add_jump` enqueue a `Move` with an arrival time (`distance * DEFAULT_MOVE_DELAY_MS`); a jump is a `Move` whose origin == target. **`piece.state` is the single source of truth for the in-flight lock**: `add_move` rejects any piece not `State.idle`, flips it to `moving`/`airborne`, and every resolution path must flip it back. Time only advances via `advance_time(ms)`, which (1) resolves path collisions — same color: the later-arriving piece is truncated one square before the shared cell; opposite colors: the **earlier** arriver at the shared cell is captured mid-flight (the later piece "sweeps" it); airborne pieces capture enemy movers that enter their square during the jump window — then (2) applies arrived moves, re-validating each against the current board (`_is_still_valid`). Returns True when a king is captured.
- **`game_engine/game.py`** — `KungFuChessGame`, the facade the UIs talk to: `move_request`, `jump_request`, `wait(ms)` (the only thing that drives the arbiter clock), `finish_game`, `game_active`. Validates via the rules engine before enqueueing with the arbiter.
- **`input/` & `textTester/`** — UI, input handling, and script parsing only; no game rules or state mutation here. `Controller` turns pixel clicks into select-then-move requests (left click = move, right click = jump); `BoardMapper` converts pixels ↔ grid coordinates.
- **`view/`** — OpenCV GUI: `GUI_runner.run_GUI(game)` wires `AssetManager` (loads `board.png` and per-piece/per-state sprite folders under `view/assets/`), `GameRenderer` (draws a frame from a `GameSnapshot` of `PieceDTO`s), and `GameLoop` (cv2 window, mouse callback, drives `wait` on a wall-clock cadence).

## Coding rules

- **Encapsulation**: touch board state only via `Board`'s public API (`get_piece_at`, `set_piece_at`, `is_cell_empty`, ...) — never `board._grid[...]` from outside `Board`. Prefix class-internal state and private helpers with a leading underscore.
- **No magic values**: business logic contains zero raw numbers or literal strings — board dimensions, timing delays, and asset properties live in module-level constants or config modules (e.g. `DEFAULT_MOVE_DELAY_MS`, not `1000`).
- **Result objects over exceptions**: high-level checks and actions return domain result objects like `MoveValidation` instead of raising. When a truly exceptional error occurs, raise a domain-specific exception (e.g. `InvalidMoveError`) — never a raw `Exception`, and never signal errors by returning `False`/`None` silently. Preserve existing public interfaces.
- **SRP & DRY**: each function does one thing (`validate_move` / `execute_move`, not one `process_move` that validates + mutates + times); each piece of logic lives in exactly one place.
- **Naming**: `snake_case` `verb_noun` functions (`validate_move`, `advance_time`), `PascalCase` classes/enums.
- Use type hints and `dataclasses` for all new code.

## Testing

- Tests live in `tests/` and mirror the source structure. Test public behaviors, not private helpers; use pytest fixtures and parameterized helpers to set up boards and game states.
- Cover: move validation and rejection reasons (assert on `MoveValidation.reason`), arbiter timing/path/collision resolution, and game lifecycle (`game_active`, `finish_game`, `wait`).
- Tests are deterministic: they never sleep — they construct boards directly (`Board([[EMPTY_CELL]*8 ...])`), enqueue moves, and call `advance_time(ms)` explicitly.

## Gotchas (current state, 2026-07)
- `piece.position` duplicates the grid location; `set_piece_at` and `move_piece` keep it in sync — never set one without the other.
