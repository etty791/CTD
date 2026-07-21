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

- **`model/`** — dumb domain state and simple transitions; no rule validation. `Board` wraps an 8x8 grid whose cells hold either a `Piece` or the string sentinel `EMPTY_CELL = '.'` (import it from `model.board`; never compare to a literal). `Piece` carries `id`, `Color`, `PieceType`, `position`, and a `State` enum: `idle`/`moving`/`captured`/`airborne` plus two cooldown states, `long_rest`/`short_rest` (`state.is_resting()` is true for either). `Position(x, y)` is **x = row, y = col**. Board mutation goes through `get_piece_at`/`set_piece_at`/`move_piece`/`is_cell_empty`; `move_piece` also marks captures and applies pawn promotion. `model/game_snapshot.py` defines the view-facing `PieceDTO` — beyond `id`/`position`/`type`/`color`/`state`, it carries `origin`, `target`, and `progress` (0.0-1.0) so the view can render a piece mid-flight; all three collapse to the piece's own position/0.0 when idle or resting.
- **`rules/`** — pure, timeless move legality. `rules_engine.validate_move(board, src, dst)` returns a frozen `MoveValidation(is_valid, reason)` dataclass (reasons are strings like `"illegal_piece_move"`, `"empty_source"`, `"game_over"`). It dispatches to per-piece strategy classes in `piece_rules.py` (`_SlidingRules` shared by Rook/Bishop/Queen). No time, no collisions, no mutation here.
- **`real_time/real_time_arbiter.py`** — the heart of the game: timing, pending moves, path-collision resolution, and post-move cooldowns. Owns a millisecond `clock` and a `pending_moves` list. `add_move`/`add_jump` enqueue a `Move` with an arrival time (`distance * DEFAULT_MOVE_DELAY_MS`); a jump is a `Move` whose origin == target. **`piece.state` is the single source of truth for the in-flight lock**: `add_move`/`add_jump` reject any piece that is not `State.idle` (this includes resting pieces, via `is_resting()`), and flip it to `moving`/`airborne` on acceptance. Time only advances via `advance_time(ms)`, which (1) resolves path collisions — same color: the later-arriving piece is truncated one square before the shared cell; opposite colors: the **earlier** arriver at the shared cell is captured mid-flight (the later piece "sweeps" it); airborne pieces capture enemy movers that enter their square during the jump window — then (2) applies arrived moves, re-validating each against the current board (`_is_still_valid`), then (3) calls `_release_expired_rests()`. A piece never returns straight to `idle` when a move concludes: `_begin_rest` puts it into `long_rest` or `short_rest` (durations `LONG_REST_DURATION_MS`/`SHORT_REST_DURATION_MS` in `real_time_config.py`) anchored to the move's `arrival_time` (not the current clock, so rests behave identically regardless of how coarsely `advance_time` is called); `_release_expired_rests` flips it back to `idle` once the rest has elapsed. A piece captured while resting is dropped, never revived. Returns True when a king is captured.
- **`game_engine/game.py`** — `KungFuChessGame`, the facade the UIs talk to: `move_request`, `jump_request` (both return `MoveValidation(False, reason="piece_resting")` if the piece is on cooldown), `wait(ms)` (the only thing that drives the arbiter clock), `finish_game`, `game_active`, `get_snapshot()`. Validates via the rules engine before enqueueing with the arbiter. `game_engine/snapshot.py`'s `GameSnapshot.get_all_pieces()` builds the `PieceDTO` list each frame, cross-referencing the arbiter's `pending_moves` to compute each piece's `origin`/`target`/`progress` for animation — it lives in `game_engine` rather than `model` because it needs `real_time` knowledge that `model` must not depend on.
- **`input/` & `textTester/`** — UI, input handling, and script parsing only; no game rules or state mutation here. `Controller` turns pixel clicks into select-then-move requests (left click = move, right click = jump); `BoardMapper` converts pixels ↔ grid coordinates.
- **`view/`** — OpenCV GUI: `GUI_runner.run_GUI(game)` wires `AssetManager` (loads `board.png` and per-piece/per-state sprite folders under `view/assets/`), `GameRenderer` (draws a frame from a `GameSnapshot` of `PieceDTO`s), `PieceAnimator` (per-piece-id, picks the sprite frame for a `PieceDTO`'s state — `STATE_ASSET_FOLDER` in `view_config.py` maps every `State` to its asset folder, including `long_rest`/`short_rest` — advancing frames by elapsed wall-clock time since the piece entered that state, looping or clamping per the asset's `graphics` config; `prune()` drops tracked pieces no longer in the snapshot), and `GameLoop` (cv2 window, mouse callback, drives `wait` on a wall-clock cadence). `GameRenderer._pixel_position` lerps a piece's pixel position between `origin`/`target` by `progress`, so in-flight pieces animate smoothly across frames even though each `render_frame` call only sees a stateless snapshot.

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
- A piece never goes `moving`/`airborne` → `idle` directly: every completed move or jump routes through `long_rest`/`short_rest` first (see `RealTimeArbiter._begin_rest`). Code that checks "is this piece free to command" must use `state.is_resting()` / `state == State.idle`, not just check for `moving`/`airborne`, or it'll let you re-issue a move during cooldown.
- `GameSnapshot`/`PieceDTO` and `GameRenderer` assume `origin`/`target`/`progress` are always populated (defaulting to the piece's own position and `0.0` when idle) — new `State` values need an entry in `STATE_ASSET_FOLDER` (`view/view_config.py`) or `PieceAnimator.frame_for` will `KeyError`.
