# Kung Fu Chess

A real-time chess variant played on a standard 8x8 board with standard chess
pieces and moves — but with no turns. Any piece can be ordered to move at any
time, moves take real time to travel across the board (1000 ms per square by
default), and pieces in flight can collide: two pieces racing for the same
square, or a piece sliding into another mid-move, resolve based on who gets
there first. The game ends the moment a king is captured.

## Features

- **No turns** — both sides can issue commands simultaneously; timing, not
  turn order, decides outcomes.
- **Moves take real time** — a move isn't instant; it travels at a fixed
  speed, so a slow response can be intercepted.
- **Mid-flight collisions** — pieces moving at the same time can capture or
  block each other before either arrives, with same-color and opposite-color
  collisions resolved differently.
- **Two front ends** — an OpenCV graphical board for interactive play, and a
  headless text-script runner for scripted/automated games and tests.

## Tech stack

- **Python 3** — core language
- **OpenCV** (`opencv-python`) — board and piece rendering, input loop
- **NumPy** — array/image support for OpenCV
- **pytest** — test suite

## Installation

A virtual environment is expected at `.venv`. From the project root:

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
```

## Running the game

Launch the OpenCV graphical board:

```powershell
.venv\Scripts\python.exe main.py
```

Left-click a piece then a destination square to move it; right-click to
jump (teleport-style move, still subject to the same rules and timing).

### Text-based script runner

`textTester/script_runner.py` can drive a game from a plain-text script
piped over stdin — useful for scripted games, debugging, or automated
scenarios without the GUI. A script has a `Board:` section describing each
square (`.` for empty, or a two-character token like `wK`, `bP` for
color + piece type) followed by a `Commands:` section of `click x y`,
`jump x y`, `wait ms`, and `print board` instructions.

## Running the tests

```powershell
.venv\Scripts\python.exe -m pytest                          # full suite
.venv\Scripts\python.exe -m pytest tests/test_board.py      # one file
.venv\Scripts\python.exe -m pytest tests/test_collisions.py::TestEnemyPathCollision::test_earlier_starter_wins_head_on
```

Tests are deterministic — they build boards and game states directly and
advance the game clock explicitly (`advance_time(ms)`), never `sleep`.

## Architecture

The codebase is layered with a single direction of dependency:

```
view / input / textTester
        |
   game_engine
        |
  rules  +  real_time
        |
      model
```

Each layer has one job, and responsibilities don't leak across the
boundaries:

- **`model/`** — dumb domain state and simple transitions, with no rule
  validation. `Board` wraps an 8x8 grid of `Piece` objects (or the
  `EMPTY_CELL` sentinel). `Piece` carries an id, color, piece type,
  position, and state (`idle` / `moving` / `captured` / `airborne`).
  `Position(x, y)` uses x = row, y = column. All board mutation goes
  through `Board`'s public API (`get_piece_at`, `set_piece_at`,
  `move_piece`, `is_cell_empty`), which also handles captures and pawn
  promotion.

- **`rules/`** — pure, timeless move legality. `rules_engine.validate_move`
  checks whether a move from one square to another is legal for the piece
  involved and returns a `MoveValidation` result (valid/invalid plus a
  reason string), dispatching to per-piece-type rule strategies in
  `piece_rules.py`. No timing, no collisions, no board mutation happens
  here.

- **`real_time/`** — the timing engine. `RealTimeArbiter` owns a
  millisecond clock and the list of moves currently in flight. Enqueuing a
  move (or jump) locks the piece (`state` is the source of truth for
  "already moving") and schedules an arrival time based on distance and
  the configured move delay. Advancing the clock resolves path collisions
  (same-color pieces racing for a square get truncated; opposite-color
  pieces racing for a square result in a capture of the earlier arriver;
  airborne pieces can capture movers that cross their square mid-jump),
  then applies any moves that have arrived, re-validating them against the
  live board.

- **`game_engine/`** — `KungFuChessGame`, the facade every front end talks
  to. It validates requested moves through the rules engine, then hands
  legal ones to the arbiter; `wait(ms)` is the only thing that advances the
  game clock; `game_active` and `finish_game` manage game lifecycle.

- **`input/` & `textTester/`** — UI-adjacent input handling only, no rules
  or state mutation. `Controller` turns mouse clicks into select/move/jump
  requests; `BoardMapper` converts pixel coordinates to board grid
  coordinates; `textTester` parses and runs the plain-text scripts
  described above.

- **`view/`** — the OpenCV GUI. `GUI_runner` wires together `AssetManager`
  (loads the board and piece sprites from `view/assets/`), `GameRenderer`
  (draws frames from a `GameSnapshot`), and `GameLoop` (the cv2 window,
  mouse callback, and wall-clock loop that drives `wait`).

## Project layout

```
CTD/
├── main.py            # entry point — launches the OpenCV GUI
├── model/             # board, piece, position — domain state
├── rules/             # move legality (rules_engine, piece_rules)
├── real_time/         # timing/collision arbiter
├── game_engine/       # game facade + snapshot for rendering
├── input/             # click handling, pixel↔grid mapping
├── textTester/        # text-script parser and runner
├── view/              # OpenCV rendering, assets, game loop
└── tests/             # pytest suite, mirrors the source layout
```

## License

MIT — see [LICENSE](LICENSE).
