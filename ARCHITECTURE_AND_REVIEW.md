# Kung Fu Chess — Architecture Reference & Code Review

*Updated 2026-07-29, branch `server` @ `648c025`. Test suite: **546 passed, 0 xfailed**.*
*Previous revision: 2026-07-28 @ `c2769b8` (485 passed, 1 xfailed).*

This document has two halves:

* **Part I — Architecture** (§1–§7): what every layer is responsible for, how the pieces
  connect, the end-to-end pipelines, and the design patterns in use.
* **Part II — Review** (§8–§15): confirmed bugs, architectural problems, inconsistencies,
  code smells, dead code, test gaps and hygiene issues — each with a file reference and,
  where it was reproduced, the exact observed behaviour.

Every claim in Part II marked **[verified]** was reproduced by running the code, not
inferred from reading it.

## What changed since the last revision

Seven commits landed between `c2769b8` and `648c025`, closing the whole of Tier 1 and
Tier 2 and most of Tier 3 from §15 of the previous revision:

| Commit | Effect |
|---|---|
| `c6914ef` | king losing a same-tick arrival race now ends the game (§8.2) |
| `e0c7d70` | captured pieces' pending moves dropped; vacate-on-move occupancy (§8.3) |
| `c2c23c9` | collision timing gate, wire bounds validation, Elo-failure isolation (§8.1/§8.4/§8.6) |
| `13cc05e` | session-lifecycle leaks + deterministic tie-break (§8.5/§8.7/§8.8/§8.9/§8.10/§8.11) |
| `c220690` | absolute move times on the wire, client-side interpolation (§4.8) |
| `445074d` | `RESIGN`, seek ack/cancel, `GameLoop` auto-exit, `EVENT` channel (§9.1/§9.2/§9.4/§9.5) |
| `648c025` | `view`↔`input` cycle broken, `Board` purified, `EMPTY_CELL` removed, dead code pruned (§10.1/§10.2/§10.3/§11.1/§13) |

**14 of the 21 numbered defects are resolved.** A resolution ledger opens Part II; every
resolved item keeps its original number so cross-references from commit messages and code
comments still land, with the fix recorded in place of the reproduction.

---

---

# PART I — ARCHITECTURE

## 1. What the system is

A real-time chess variant with **no turns**. Any piece may be ordered at any moment; moves
take real time to travel (`DEFAULT_MOVE_DELAY_MS = 1000` ms per square); pieces collide
*mid-flight*; a piece that completes a move enters a cooldown before it can be commanded
again. The game ends when a king is captured.

It ships as **two products over one engine**:

| Mode | Entry point | Who owns the clock | Who validates |
|---|---|---|---|
| **Local** | `main.py` | the GUI loop (`GameLoop.run` → `game.wait(ms)`) | in-process engine |
| **Networked** | `server.main:app` + `python -m client` | the server (`AsyncClock.every` → `engine.wait`) | the server, authoritatively |
| **Scripted** | `textTester/script_runner.py` | the script (`wait 3000`) | in-process engine |

The critical design property: **`view/` and `input/` cannot tell the difference.**
`client/remote_game.py` implements exactly the surface the GUI and `Controller` consume
from a local `KungFuChessGame`, so the entire presentation stack runs unmodified over the
wire, for players and spectators alike.

### Commands

```powershell
.venv\Scripts\python.exe -m pytest                    # 546 passed
.venv\Scripts\python.exe main.py                      # local single-process game
.venv\Scripts\python.exe -m uvicorn server.main:app   # server on ws://127.0.0.1:8000/ws
.venv\Scripts\python.exe -m client                    # REPL, then the GUI once a game starts
```

Env: `CTD_DB_PATH` (default `server/data/ctd.db`), `CTD_SERVER_URL` (default
`ws://127.0.0.1:8000/ws`). Dependencies are now declared in `requirements.txt`.

---

## 2. Layer map

**No package-level violation of the documented layering exists** — and as of `648c025` the
one real cycle is gone too.

```
                      ┌──────────────┐
   textTester ───────►│              │
   view ─────────────►│ game_engine  │──► rules ──┐
   input ────────────►│  (facade)    │──► real_time ──┐
        ▲             └──────┬───────┘              │  │
        │                    │                      ▼  ▼
   client ──────────────────►└────────────────────► model
        │                                          ▲
        └──► shared ───────────────────────────────┘
                ▲
   server ──────┴──► game_engine, events, model
```

Actual measured edges:

| package | imports |
|---|---|
| `model` | *(nothing)* |
| `rules` | `model` |
| `events` | `model` |
| `real_time` | `model`, `rules`, `events` |
| `game_engine` | `model`, `rules`, `real_time`, `events` |
| `shared` | `model` |
| `server` | `model`, `events`, `game_engine`, `shared` |
| `client` | `model`, `events`, `shared` |
| `view` | `model`, `events`, `shared`, `input` |
| `input` | `shared` |
| `textTester` | `model`, `game_engine`, `input`, `view` |

The rules that hold, and why they matter:

* `shared/` never imports `game_engine` / `real_time` / `server`. This is what lets the
  client depend on the wire contract without dragging in an engine. The one place that
  needs both (`GameSnapshot` → `StatePayload`) lives in `server/encoding.py`.
* `client/` never imports `game_engine` / `real_time` / `rules`. The server is the sole
  authority; the client has no shadow engine to desync.
* `model/` imports nothing. It is the leaf.
* `input/` no longer imports `view/` — `BoardMapper` takes `DEFAULT_BOARD_SIZE` from
  `shared/protocol_config.py`, so the old `view` ↔ `input` cycle is broken. `view/` still
  imports `input/` (one direction only), which is what `GUI_runner` wiring needs.

---

## 3. Layer-by-layer responsibilities

### 3.1 `model/` — dumb state, no rules

| File | Responsibility |
|---|---|
| `position.py` | `Position(x, y)` where **x = row, y = col**. Value equality + hash (so positions work as dict keys and in `set` intersections, which the collision detector relies on). |
| `piece.py` | `Piece(id, color, type, position, state)`. `State` enum: `idle`, `moving`, `captured`, `airborne`, `long_rest`, `short_rest`; `state.is_resting()` covers the two cooldowns. |
| `board.py` | 8×8 grid whose cells hold **either a `Piece` or `None`**. Public API: `get_piece_at` / `set_piece_at` / `is_cell_empty` / `is_within_boundaries` / `move_piece` / `place_piece` / `is_friendly` / `is_enemy`. It marks nothing captured and promotes nothing. |
| `game_snapshot.py` | `PieceDTO` — the view-facing piece record. Beyond identity it carries `origin`, `target`, `progress` (0.0–1.0) **and** `move_start_ms` / `move_arrival_ms`. |

**The empty cell is `None`.** The old `EMPTY_CELL = '.'` string sentinel is gone
(`648c025`); `get_piece_at` returns `Optional[Piece]` and `is_cell_empty` is
`get_piece_at(...) is None`. The `'.'` token survives only in the textTester DSL as
`tester_config.EMPTY_TOKEN`, where it is a *syntax* element, not a domain value.

**`Board` performs no game logic.** `move_piece` relocates and overwrites; its docstring
states outright that marking a displaced occupant `State.captured` is the arbiter's job
(`RealTimeArbiter._mark_captured`), because only the arbiter can also evict that occupant's
own pending move. Promotion moved out to `rules/promotion.py::is_promotion_square` — a pure
predicate the arbiter calls after placing a piece.

**Why `PieceDTO` carries both `progress` and absolute times:** the local GUI samples the
engine ~30×/sec, so a sampled `progress` is always fresh. The networked client receives
frames *on change* — possibly a full second apart — so a frozen fraction would visibly
stall. The absolute bounds let the receiver re-derive `progress` at render rate. Both
collapse to `position` / `0.0` / `None` when the piece is at rest.

**`piece.position` duplicates the grid location.** `set_piece_at` and `move_piece` keep the
two in sync; nothing else may set one without the other.

### 3.2 `rules/` — pure, timeless legality

Two entry points, and the distinction between them matters:

* `validate_move(board, src, dst)` — bounds-checks both endpoints (`OUT_OF_BOUNDS`),
  requires a non-empty source (`EMPTY_SOURCE`), then delegates.
* `validate_piece_move(board, piece, dst)` — keyed off the **piece**, not its board cell.
  This is what the arbiter re-validates in-flight moves with, because a mid-flight piece has
  already vacated its origin square (§3.4) and so has no cell to look up.

Both return the frozen `MoveValidation(is_valid, reason)`; reasons come from the
`MoveReason` StrEnum (`OK`, `EMPTY_SOURCE`, `ILLEGAL_PIECE_MOVE`, `GAME_OVER`,
`PIECE_RESTING`, `INVALID_MOVE`, `INVALID_JUMP`, `OUT_OF_BOUNDS`).

Dispatch is a **Strategy table**: `_rules: Dict[PieceType, PieceRules]`, each implementing
`legal_destinations(board, piece) -> Set[Position]`. `_SlidingRules` is shared by
Rook/Bishop/Queen with only a `directions` tuple differing; `QueenRules.directions` is
literally `RookRules.directions + BishopRules.directions`.

`promotion.py` holds `is_promotion_square(board, piece)` — pawn on its far back rank —
which is where the promotion rule lives now that `Board` no longer applies it.

**No time, no collisions, no mutation here.**

### 3.3 `events/` — synchronous pub/sub

`EventBus`: `subscribe` / `unsubscribe` / `publish`, keyed on `type(event)`. Handlers run
**synchronously, in subscription order**, inside the publisher's call stack. A handler that
raises is logged and skipped so it cannot block the rest.

The frozen event dataclasses in `game_events.py`:

| Event | Meaning |
|---|---|
| `GameStarted` | engine constructed |
| `GameEnded(winner)` | a king was captured |
| `MoveStarted(move_id, piece_id, src, dst)` | a move/jump was accepted |
| `MoveCompleted(...)` | a move arrived and was applied |
| `MoveTruncated(move_id, piece_id, target, arrival_time_ms)` | shortened mid-flight by a same-colour blocker; **still flying**, to a nearer square |
| `MoveAborted(move_id, piece_id, position)` | ended without reaching any new cell |
| `RestEnded(piece_id, position)` | cooldown elapsed, piece is `idle` again |
| `PieceCaptured(..., capturing_move_id)` | correlates a capture with the move that caused it |

`ScoreChanged` was **removed** in `648c025` — it had no subscribers, and `ScoreTracker` now
simply tallies without re-publishing (which also retires the re-entrant-publication smell).
The renderer and `StatePayload` both read scores from the snapshot.

**The arbiter is the only publisher of move/capture/end events.** Everything reactive —
scores, move log, scene overlays, sounds, server-side finalization, network broadcasting —
subscribes rather than being called. This is the seam that makes the same engine drive a
GUI and a WebSocket server without either knowing about the other, and — since `445074d` —
it is also what feeds the wire's `EVENT` channel.

### 3.4 `real_time/real_time_arbiter.py` — the heart

Owns a millisecond `clock`, a `pending_moves` list, a `_resting` list, and a monotonically
increasing `_next_move_id`.

**`piece.state` is the single source of truth for the in-flight lock.** `add_move` /
`add_jump` reject any piece not in `State.idle` (which subsumes resting), and flip it to
`moving` / `airborne` on acceptance. There is deliberately no second scan of
`pending_moves` for a matching origin.

**Capture is single-sourced.** `_mark_captured(piece, capturing_move_id)` is the *only*
place a piece becomes `State.captured`. It is idempotent, publishes `PieceCaptured`, and —
critically — calls `_drop_moves_for(piece)` so a corpse can never again truncate, capture,
or be re-captured. This is what closed §8.3.

Time advances **only** through `advance_time(ms)`, in four phases:

```
advance_time(ms):
  clock += ms
  1. _resolve_path_collisions()      → may capture / truncate pieces mid-flight
                                       (applied only when resolution_time <= clock)
  2. _vacate_departed_origins()      → a mover's origin cell frees up one square in
  3. _pop_arrived_moves()            → group by target
       len > 1 → _resolve_collision()  (defensive same-tick fallback)
       len = 1 → _resolve_single()     → _is_still_valid() → _apply_move() | _abort_move()
  4. _release_expired_rests()        → publishes RestEnded per released piece
  returns: True iff a king was captured
```

**Vacate-on-move occupancy.** At `move.start_time + DEFAULT_MOVE_DELAY_MS` a mover's origin
square is emptied — other pieces then pass through or land on it as if the mover weren't
there. `piece.position` is *not* updated (it still reads the origin until the piece lands),
which is exactly why in-flight re-validation goes through `validate_piece_move` rather than
`validate_move`. Airborne pieces never vacate: they hold their square for the whole jump
window so they can keep intercepting.

A move that can no longer complete does **not** teleport back: `_abort_move` /
`_retreat_vacated_move` walks backward along the move's own path to the nearest free square
(publishing `MoveTruncated`), or, if none is free, the piece is captured outright.

Because a vacated piece is absent from the board, `GameSnapshot.get_all_pieces()` unions in
any `pending_moves` the board scan missed, reporting them at `move.origin` — otherwise they
would flicker out of existence mid-move.

**Collision semantics** (`_resolve_path_collisions`, all pairs of pending moves). Each pair
produces a `(resolution_time, outcome, payload)` fate; a piece keeps the *earliest* fate,
and **a `CAPTURE` fate is applied only once `self.clock` reaches `resolution_time`** —
truncation still applies early, because a piece needs to know where it is stopping:

| Situation | Outcome |
|---|---|
| same colour, shared cell | the **later** arriver is truncated one square before the shared cell (`MoveTruncated`); if that leaves it at its origin, the move is aborted instead |
| opposite colours, shared cell | the **earlier** arriver at that cell is captured mid-flight — the later piece "sweeps" it |
| exact tie (`t_a == t_b`) | the **lower `move_id`** wins: the piece ordered first survives, and exactly one of the pair is resolved |
| one piece airborne | an enemy mover entering the jumper's square during the jump window is captured; a friendly one is truncated |
| both airborne | no interaction (a jump never leaves its square) |

**Cooldowns.** A piece never goes `moving`/`airborne` → `idle` directly. `_begin_rest` puts
it into `long_rest` (a move, `2 × DEFAULT_MOVE_DELAY_MS`) or `short_rest` (a jump,
`1 × DEFAULT_MOVE_DELAY_MS`), anchored to the move's **`arrival_time`, not the current
clock** — so a rest behaves identically whether time advanced in one 5000 ms step or a
hundred 50 ms ones. `_release_expired_rests` runs at the *end* of `advance_time`, so a rest
that both starts and expires inside one large step is released in that same call.

**Path geometry.** `_path_cells(origin, target)` returns the cells from origin (exclusive)
to target (inclusive). A non-sliding move (knight) has no intermediate squares, so it
returns `[target]` — without that special case, the unit-step walk would never terminate.
`_move_distance` mirrors it: a knight is one leap regardless of Chebyshev distance.

**Timing.** `_time_at_cell(move, path, cell) = move.start_time + (index+1) × DELAY`. This
is the whole temporal model: a fixed-speed walk along a fixed path, so any crossing time is
computable in closed form the moment both moves exist.

### 3.5 `game_engine/` — the facade the UIs talk to

`KungFuChessGame` owns the `Board`, the `EventBus` (`game.events`), the `RealTimeArbiter`,
and the two engine-side subscribers.

| Method | Contract |
|---|---|
| `move_request(origin, target)` | `MoveValidation`. Rejects `GAME_OVER`, then rules-validates (bounds included), then `PIECE_RESTING`, then hands to the arbiter |
| `jump_request(pos)` | same shape; `EMPTY_SOURCE` / `PIECE_RESTING` / `INVALID_JUMP` |
| `wait(ms)` | **the only thing that drives the arbiter clock**; calls `finish_game()` on a king capture |
| `piece_color_at(pos)` | ownership query, so the server needn't reach into `board` |
| `get_snapshot()` | a fresh `GameSnapshot` |
| `game_active`, `finish_game()` | lifecycle |

Subscribers wired here:

* **`ScoreTracker`** — tallies `PieceCaptured` by `score_config.PIECE_VALUES`. KING is
  deliberately absent from the value table: a king capture ends the game rather than
  scoring.
* **`MoveLog`** — ordered `MoveLogEntry` list. `was_capture` is correlated by `move_id`:
  `PieceCaptured` always fires *before* the `MoveCompleted` of the move that caused it
  (both published synchronously from the same arbiter call), so the pending-capture set is
  always populated in time.

`snapshot.py`'s `GameSnapshot` builds the `PieceDTO` list by scanning the board, unioning in
vacated in-flight pieces, and cross-referencing `arbiter.pending_moves` via a `_Motion`
record for `origin`/`target`/`progress`/times. It lives in `game_engine` rather than `model`
precisely because it needs `real_time` knowledge that `model` must not have.

`game_engine/payloads.py` (`MoveValidationPayload`) was deleted in `648c025` — it was used
only by its own test.

### 3.6 `shared/` — the wire contract

Imported by **both** sides; depends on `model/` only.

* **`protocol.py`** — `Envelope(type, payload, game_id)` wraps every frame; `MessageType`
  enumerates `register`/`login`/`move`/`jump`/`state`/`create_room`/`join_room`/`play`/
  `game_start`/`game_over`/`resign`/`cancel_seek`/`event`/`error`. The vestigial `chat` and
  `auth` members are gone; `resign`, `cancel_seek` and `event` are new and all three are
  live.
* **`messages.py`** — one pydantic model per payload.
  * `PositionPayload.x/y` are `Field(ge=0, lt=BOARD_SIZE)` — the wire refuses an
    out-of-board coordinate before it can reach a grid index (§8.4).
  * `PiecePayload` carries `move_start_ms`/`move_arrival_ms` **instead of** a sampled
    `progress`, and `StatePayload.server_time_ms` is the timebase they're measured against.
  * `EventPayload(event_type, data)` is deliberately generic — a free-form `data` dict
    rather than one model per event dataclass — so `shared/` gains no dependency on
    `events/`. Encoding and decoding the real dataclasses live on the two sides that
    already have them (`server/encoding.py`, `client/remote_game.py`).
* **`protocol_config.py`** — values both sides must interpret identically: `Status`, `Role`,
  `ROOM_STATUS_WAITING`, `MATCH_TIMEOUT_MS`, and now `DEFAULT_BOARD_SIZE` (re-exporting
  `model.board.BOARD_SIZE`) and `MS_PER_SECOND`. Those last two used to live in
  `view/view_config.py`, which is what forced `client/` and `input/` to import the rendering
  config for domain constants. Server-only knobs live in `server/server_config.py`.

### 3.7 `server/` — FastAPI + WebSockets, authoritative engine per game

| File | Responsibility |
|---|---|
| `main.py` | accepts sockets on `WS_PATH`, validates each frame into an `Envelope`, hands it to `dispatch`; `lifespan` starts/stops the `PersistenceWorker`; a `try/except/finally` guarantees `_handle_disconnect` runs on *any* exit path |
| `dispatcher.py` | `MessageType → coroutine` table filled by `@register(...)`; `main.py` imports `server.handlers` purely for that side effect |
| `handlers.py` | module-level singletons (`registry`, `room_manager`, `clock`, `persistence`, `logged_in_usernames`, `_pending_seek_timers`) + one handler per message |
| `connection.py` | wraps a socket with an `asyncio.Lock` so a broadcast task and a handler reply cannot interleave frames |
| `session.py` | `PlayerSession` binds a username to a `Connection` |
| `game_session.py` | one live game: two players + observers, server ticking, event-driven broadcasting, event forwarding, the end-of-game → Elo → `GAME_OVER` pipeline |
| `game_registry.py` | `game_id → GameSession` and `player_id → game_id` maps |
| `rooms.py` | pure, synchronous room membership + the ELO seek pool; returns result objects the async layer acts on |
| `async_clock.py` | the one timing source (`every` for ticks, `after` for the seek timeout), so timing is fakeable wholesale in tests |
| `elo.py` | pure Elo math (`K_FACTOR = 32`, `DEFAULT_RATING = 1200`) |
| `encoding.py` | `GameSnapshot → StatePayload` **and** engine event → `EventPayload`; the one place that knows both sides |
| `persistence/` | `PersistenceWorker` owns `Database` + `UserRepository` on **one** dedicated thread |

**Why the receive loop is fully guarded.** `websocket_endpoint` catches
`WebSocketDisconnect`, catches and logs any other `Exception`, and does cleanup in a
`finally`. Before `c2c23c9` an unhandled error escaped the endpoint entirely, so the
username stayed in `logged_in_usernames` (locking the account out for the process lifetime)
and the `GameSession` ticked on with no reader.

**Why broadcasting is event-driven, not tick-driven.** The engine still advances real time
every `TICK_MS = 50`, but `_on_tick` calls `broadcast_state()` only when the engine's bus
published one of `STATE_CHANGING_EVENTS` during that tick — coalesced through `_mark_dirty`,
which raises a single flag so a capture (`MoveCompleted` + `PieceCaptured`) costs one frame,
not two — or when `MAX_STATE_INTERVAL_MS = 1000` has elapsed without one (a resync
heartbeat). `broadcast_state()` resets the flag *and* the timer up front, so an out-of-band
send (a move handler's echo, the initial frame) counts as the heartbeat instead of leaving a
duplicate queued.

**The `EVENT` channel** (`445074d`). `FORWARDED_EVENTS` — `STATE_CHANGING_EVENTS` minus
`GameEnded` — are additionally re-emitted to every recipient as their own `EVENT` envelope.
A coalesced `STATE` diff is the right shape for rendering but the wrong shape for cues; the
client's `SoundPlayer` and any future move log need to know *what happened*, not just what
the board looks like now. `GameEnded` is excluded because `GAME_OVER` already carries it.

**Every fan-out is failure-isolated.** `broadcast_state`, `_broadcast_event` and
`_finalize` all use `asyncio.gather(*sends, return_exceptions=True)`, so one half-closed
socket can no longer starve every recipient behind it in the list (§8.11).

**Why the persistence worker exists.** sqlite connections are thread-affine and blocking;
scrypt is CPU-heavy. Neither may touch the event loop. `ThreadPoolExecutor(max_workers=1)`
serializes every job on the same thread — exactly what sqlite requires, and it makes
`self._repo` (assigned inside a job) safely visible to all later jobs. Jobs return
`Future`s: `future.result()` from sync code, `await asyncio.wrap_future(...)` from async.

**Layering rule inside the server:** `GameSession` must **not** know about `GameRegistry` or
`RoomManager`. Cleanup is injected as the async `on_finalize` callback.

### 3.8 `client/` — `python -m client`

* **`Shell`** — a dispatch-dict REPL (`register` / `login` / `play` / `room [id]` / `help` /
  `quit`) that hands off to the same OpenCV GUI once a game starts.
* **`ServerConnection`** — a background daemon thread running its own asyncio loop and the
  `websockets` client. Sends are marshalled with `run_coroutine_threadsafe`; inbound frames
  either go straight to the active `RemoteGame` (`STATE` / `EVENT` / `GAME_OVER`) or onto a
  queue the main thread blocks on. `wait_for` polls in bounded 0.5 s slices so Ctrl+C stays
  responsive (an unbounded C-level `queue.get()` doesn't check for pending signals until it
  returns). A `STATE` that arrives before `set_active_game` has run is **held** in
  `_pending_state` and replayed on attach — dropping it could leave the board empty until
  the next real change.
* **`RemoteGame`** — implements exactly `move_request` / `jump_request` / `wait` /
  `get_snapshot` / `game_active` / `events` / `board`, plus `resign()` (which `GameLoop`
  calls through `getattr`, since the local engine has no server to concede to). Inbound
  `EVENT` frames are decoded back into the real `events/` dataclasses and republished on the
  local bus, which is what gives the networked GUI its sounds.
* **`RemoteGameState`** — one decoded frozen frame, doubling as the snapshot *and* the piece
  index. `get_all_pieces()` recomputes `progress` on every call from each piece's
  `move_start_ms`/`move_arrival_ms` against `server_time_ms` plus wall-clock time since
  receipt, clamped to 1.0. Latency shifts every piece by the same constant, so no clock sync
  is needed.
* **`RemoteBoardView`** — the read-only slice of `Board` the `Controller` needs.

### 3.9 `view/` and `input/`

`run_GUI(game)` wires: `AssetManager` (board + per-piece/per-state sprite folders),
`GameRenderer` (draws a frame from `PieceDTO`s plus the two side score panels),
`PieceAnimator` (per-piece-id, advances sprite frames by wall-clock time since the piece
entered its state, looping or clamping per the asset's `graphics` config; `prune()` drops
vanished pieces), `SceneAnimator` (board-level intro/victory overlays driven by
`GameStarted`/`GameEnded`), `SoundPlayer` (one fire-and-forget `winsound` clip per event
type), and `GameLoop` (cv2 window, mouse callback, wall-clock `wait` cadence).

`GameLoop` now owns two keys — `KEY_QUIT` (`q`) and `KEY_RESIGN` (`r`) — and exits on its
own via `_should_exit`: the `q` key, the window being closed, **or** `not game.game_active`
once `scene_animator.is_active()` has gone false, so the victory overlay plays to completion
and then the window closes itself (§9.5).

`GameRenderer._pixel_position` lerps between `origin` and `target` by `progress`, offset by
the left score panel's width — which is why `GameLoop._mouse_callback` subtracts
`renderer.score_panel_width` before handing pixels to the controller.

`Controller` turns clicks into select-then-move (left = move, right = jump) and reads
`game.board` only through `is_within_boundaries` / `is_cell_empty` / `get_piece_at` — the
three methods `RemoteBoardView` reimplements.

### 3.10 `textTester/`

A stdin DSL: a `Board:` section of tokens (`.`, `wK`, `bP`, …) then a `Commands:` section
(`click x y`, `jump x y`, `wait ms`, `print board`, `print score`). `VALID_TOKENS` is
*derived* from the `Color` × `PieceType` enums rather than spelled out, and `EMPTY_TOKEN`
is explicitly documented as a DSL symbol distinct from `Board`'s internal `None`. Commands
map to a dispatch dict over the same `Controller` the GUI uses, at a fixed 100 px/square.

---

## 4. The pipelines

### 4.1 Local move — click to pixels

```
cv2 mouse event
  → GameLoop._mouse_callback(x - score_panel_width, y)
  → Controller.handle_click → BoardMapper.pixels_to_logic → Position(row, col)
  → (first click selects; second click issues)
  → KungFuChessGame.move_request(origin, target)
      → validate_move(board, origin, target)          [rules; bounds + legality]
      → piece.state.is_resting()?  → PIECE_RESTING
      → RealTimeArbiter.add_move(piece, origin, target)
          → piece.state = moving; pending_moves.append(Move)
          → publish MoveStarted ──► SoundPlayer
  … meanwhile, every frame …
  → GameLoop: elapsed_ms → Controller.handle_wait → game.wait(ms)
      → arbiter.advance_time(ms)   [collisions → vacate → arrivals → rest release]
  → game.get_snapshot().get_all_pieces()
  → GameRenderer.render_frame  → PieceAnimator.frame_for + _pixel_position lerp
```

### 4.2 Networked move — the full round trip

```
CLIENT (main thread)                     SERVER (event loop)
────────────────────                     ───────────────────
Controller.handle_click
  → RemoteGame.move_request
      → Envelope(MOVE, MovePayload)      ← PositionPayload bounds-checked here
      → ServerConnection.send
          → run_coroutine_threadsafe ───► websocket_endpoint receive loop
                                            → Envelope.model_validate_json
                                            → dispatch → handle_move
                                                • authenticated?
                                                • in a game?  observer?
                                                • MovePayload.model_validate
                                                • engine.piece_color_at == your colour?
                                                • engine.move_request(...)
                                                    → arbiter.add_move
                                                    → publish MoveStarted
                                                        ├─► _mark_dirty
                                                        └─► _on_forwarded_event → EVENT
                                                • await game.broadcast_state()   ← immediate echo
                                                     → encoding.state_payload_from_snapshot
                                                     → gather(send to every recipient)
  ServerConnection._route  ◄──────────────────────────────────┘
    → STATE  → RemoteGame.apply_state (under a lock, whole-object swap)
    → EVENT  → decode to an events/ dataclass → republish on the local bus → SoundPlayer
  GameLoop next frame
    → RemoteGameState.get_all_pieces()  ← progress recomputed from absolute times
    → identical GameRenderer path as local
```

### 4.3 Server tick & broadcast

```
AsyncClock.every(TICK_MS=50)
  → GameSession._on_tick(elapsed_ms)          # measured off the loop clock, not assumed
      → engine.wait(elapsed_ms)
          → arbiter.advance_time
              → publishes MoveStarted/Completed/Truncated/Aborted/PieceCaptured/RestEnded/GameEnded
                  ├─► GameSession._mark_dirty        → _dirty = True   (coalescing)
                  ├─► GameSession._on_forwarded_event→ create_task(_broadcast_event)
                  ├─► ScoreTracker
                  ├─► MoveLog
                  └─► GameSession._on_game_ended     → _ended gate → submit Elo job
      → _ms_since_broadcast += elapsed_ms
      → if _dirty or _ms_since_broadcast >= MAX_STATE_INTERVAL_MS:
             reset; create_task(broadcast_state())
      → if not engine.game_active:
             cancel_ticking(); create_task(_finalize(KING_CAPTURED))
```

### 4.4 Auth

```
REGISTER → CredentialsPayload
  → persistence.submit(repo.create_user)      [worker thread]
      → scrypt(password, os.urandom(16))      N=2^14, r=8, p=1, dklen=64
      → INSERT … (sqlite3.IntegrityError → CreateUserResult(ok=False, USERNAME_TAKEN))
  → AuthAckPayload(status=ok)                 (registering does NOT log you in)

LOGIN → already logged in (this conn, or the username globally)? → error
  → repo.authenticate → constant-time hmac.compare_digest
  → PlayerSession(username, conn)             (sets conn.player_session as a side effect)
  → logged_in_usernames.add(username)
  → AuthAckPayload(status=ok, rating)
```

Failure is deliberately undifferentiated (`ERROR_BAD_CREDENTIALS` for both no-such-user and
bad-password) to avoid username enumeration.

### 4.5 Matchmaking and rooms

```
PLAY  → rating = await persistence(repo.get_rating)
      → rating is None → ERROR_ACCOUNT_NOT_FOUND        (no longer a TypeError, §8.10)
      → room_manager.seek(session, rating)
          → _find_opponent: waiting seekers within MATCH_ELO_RANGE=100, nearest wins
          → matched?  new room, seat opponent (waited first) = White, caller = Black
      → matched  → _start_game_from_room
        no match → send PLAY ack (queued)                (§9.2)
                 → _pending_seek_timers[player] = clock.after(MATCH_TIMEOUT_MS, _on_seek_timeout)

CANCEL_SEEK → cancel the pending timer, room_manager.cancel_seek, echo CANCEL_SEEK

CREATE_ROOM → mints a 6-char Crockford-base32 id; creator seated White
JOIN_ROOM   → seat 2 free → Black, should_start_game=True → _start_game_from_room
            → otherwise   → observer: game.add_observer + registry.add_observer,
                            GAME_START(role=observer) then a *personal* STATE frame

_start_game_from_room:
  registry.create_game(...)  → GameSession + start_ticking
  room.game_id = game.id
  GAME_START to both players (with colour)
  await game.broadcast_state()          ← the initial frame
```

### 4.6 End of game → Elo → `GAME_OVER`

Two idempotent gates, because the arbiter can publish `GameEnded` **twice** for one game
(once from path-collision resolution, once from arrival):

```
_ended     — first conclusion wins; guards the Elo submission to exactly one job
_finalized — first _finalize wins; guards the GAME_OVER broadcast + cleanup

king capture:   advance_time → True → engine.finish_game()
                _on_game_ended (sync bus handler) → _ended, _winner, _submit_elo
                _on_tick sees not game_active → cancel_ticking → create_task(_finalize)

resign:         handle_resign → finalize_by_forfeit(opponent's colour, "resigned")
forfeit:        finalize_by_forfeit(winner, reason)
                → cancel_ticking, engine.finish_game(), _ended, _submit_elo, await _finalize

_finalize:      _finalized = True
                try: await the Elo future → GameResultRatings
                except: log, continue with empty rating_changes     ← §8.6
                → GameOverPayload(winner, reason, rating_changes[])
                → gather(send to every recipient, return_exceptions=True)
                → await on_finalize(self)
                     → registry.remove(game.id)
                     → room_manager.leave(every player AND every observer)   ← §8.7/§8.8
```

`apply_game_result` reads both ratings, applies symmetric Elo, and writes both rows in one
transaction. A failed Elo job no longer takes the whole pipeline down with it: the players
are always told the game ended, with empty rating changes if persistence failed.

### 4.7 Disconnect

```
websocket_endpoint finally:            ← runs on WebSocketDisconnect *and* any other error
  manager.remove(conn.id)
  conn.player_session is not None → _handle_disconnect(session)
      → logged_in_usernames.discard(player_id)
      → registry.get_game_for_player(player_id)
          in a game as a PLAYER    → finalize_by_forfeit(opponent's colour, "opponent_disconnected")
          in a game as an OBSERVER → game.remove_observer
                                     + registry.remove_player_mapping
                                     + room_manager.leave(session)      ← §8.9
          not in a game            → room_manager.leave(session)
```

### 4.8 Rendering & interpolation

Local: `progress` comes straight from the snapshot (`(clock - start) / duration`, clamped).

Networked: `progress` is **not on the wire**. `RemoteGameState._progress_of` computes
`(server_time_ms + (now - received_at) × 1000 - move_start_ms) / (arrival - start)`,
clamped to `[0, 1]`. This is what keeps motion smooth at frame rate off frames that arrive
sparsely, and why a piece parks on its target square rather than sliding past it when the
arrival frame is still in flight.

---

## 5. Design patterns in use

| Pattern | Where | Note |
|---|---|---|
| **Layered architecture** | the whole tree | one direction of dependency, verified; the last cycle removed in `648c025` |
| **Facade** | `KungFuChessGame` | hides board + rules + arbiter + bus behind 7 methods |
| **Strategy** | `rules/piece_rules.py` | `PieceRules` ABC, one class per piece, table-dispatched |
| **Template Method (light)** | `_SlidingRules` | shared walk, subclasses supply `directions` |
| **Observer / Pub-Sub** | `EventBus` | the seam between the engine and every reactive consumer — and now the wire's `EVENT` channel |
| **Adapter** | `RemoteGame`, `RemoteBoardView` | make a socket look like a local engine and a local board |
| **DTO** | `PieceDTO`, all of `shared/messages.py` | decouples internal state from what crosses a boundary |
| **Result Object** | `MoveValidation`, `RemoteMoveResult`, `AuthResult`, `CreateUserResult`, `RoomJoinResult`, `SeekResult`, `LeaveResult`, `GameResultRatings` | errors are returned, not raised |
| **Registry / Decorator registration** | `dispatcher.register` | `MessageType → handler`, populated by import side effect |
| **Command / dispatch dict** | `Shell._commands`, `script_runner.COMMANDS_TO_ACTIONS` | same shape on both |
| **Repository** | `UserRepository` | all SQL behind one object |
| **Active Object / Worker thread** | `PersistenceWorker` | serializes blocking work off the loop |
| **Dependency Injection** | `on_finalize`, `AsyncClock`, `EventBus` (optional) | what keeps `GameSession` from knowing the registry, and what makes tests deterministic |
| **Immutable snapshot** | `RemoteGameState` (frozen) | whole-object swap between threads, no partial reads |
| **Memento (light)** | `GameSnapshot` | stateless read model rebuilt per call |
| **Idempotent gate** | `_ended` / `_finalized`, `_mark_captured` | the standing answer to "this can fire twice" |

The **string-sentinel Null Object** (`EMPTY_CELL = '.'`) that headed this table in the
previous revision no longer exists — `None` and `Optional[Piece]` replaced it.

---

## 6. Concurrency model

| Context | Thread | Rules |
|---|---|---|
| engine, arbiter, rules, `RoomManager` | caller's | **fully synchronous and I/O-free** |
| handlers, `GameSession`, `AsyncClock`, `Connection` | server event loop | async |
| sqlite + scrypt | `PersistenceWorker`'s single thread | never the loop |
| bus handlers | whoever published | synchronous; `GameSession._on_forwarded_event` bridges to async by scheduling a task |
| client network | daemon thread + own loop | `run_coroutine_threadsafe` in, `queue.Queue` out |
| client GUI/REPL | main thread | reads `RemoteGameState` under a lock |

`Connection._send_lock` serializes a broadcast task against a handler reply so their frames
cannot interleave on one socket.

---

## 7. Test architecture

`pytest.ini` sets `testpaths=tests`, `pythonpath=. tests`. **`async def` tests work without
pytest-asyncio**: `tests/conftest.py` installs a `pytest_pyfunc_call` hook that runs each
coroutine test via `asyncio.run`.

Determinism is structural, not incidental: tests never sleep. They construct boards
directly, enqueue moves, and call `advance_time(ms)` explicitly. Server tests fake the clock
(recording `.every`/`.after` and firing them by hand), fake the persistence worker
(`_InertPersistence` / `_CannedPersistence` / `_RealPersistence` against a `tmp_path`
sqlite), and drive scheduled `create_task` work with a `flush_tasks()` helper.

The suite grew from 30 to 34 files and from 485 to 546 tests, closing three of the five
coverage gaps in the previous revision: `tests/test_main.py` (the websocket endpoint and
its disconnect paths), `tests/test_game_loop.py` and `tests/test_scene_animator.py` (the
first real `view/` coverage), and `tests/test_client_network.py`. `tests/test_promotion.py`
covers the extracted rule.

`tests/ultra_tests.py` is not collected by the default run (it doesn't match `test_*.py`);
it's a standalone scenario script.

---

---

# PART II — REVIEW

Severity key: **S1** = corrupts game state or hangs a player · **S2** = wrong behaviour a
user will hit · **S3** = latent / edge case · **S4** = smell, no user impact.

## 8. Confirmed bugs

### Resolution ledger

| # | Was | Now |
|---|---|---|
| 8.1 | S1 collisions resolved at enqueue time | ✅ **fixed** — `resolution_time > clock` gate; xfail flipped to passing |
| 8.2 | S1 king lost in an arrival race didn't end the game | ✅ **fixed** — `_destroy_in_transit` owns the king check |
| 8.3 | S1 ghost moves after a piece was captured | ✅ **fixed** — `_mark_captured` + `_drop_moves_for`, single-sourced |
| 8.4 | S1 out-of-range wire coordinates crashed the socket | ✅ **fixed** — `Field(ge=0, lt=BOARD_SIZE)`, `OUT_OF_BOUNDS`, `try/except/finally` |
| 8.5 | S2 head-on ties annihilated both pieces | ✅ **fixed** — lowest `move_id` wins |
| 8.6 | S1 a failed Elo job killed the `GAME_OVER` pipeline | ✅ **fixed** — the await is guarded, players are always told |
| 8.7 | S2 spectator locked out after their game ended | ✅ **fixed** — observers leave the room at finalize |
| 8.8 | S2 zombie rooms with a stale `game_id` | ✅ **fixed** — same cause; the room now closes |
| 8.9 | S2 observer disconnect never left the room | ✅ **fixed** — `_handle_disconnect` calls `leave` |
| 8.10 | S2 `handle_play` crashed on a null rating | ✅ **fixed** — `ERROR_ACCOUNT_NOT_FOUND` |
| 8.11 | S2 broadcast aborted on the first dead recipient | ✅ **fixed** — `gather(..., return_exceptions=True)` |
| 8.12 | S3 `MoveLog._pending_captures` unbounded | ⬜ **open** |
| 8.13 | S3 `_release_expired_rests` drops entries silently | ⬜ **open** (downgraded to S4) |
| 8.14 | S3 `Position.__eq__` raises on a non-`Position` | ⬜ **open** |

### 8.1 [S1] Collisions resolved at *enqueue* time, not at collision time — ✅ FIXED (`c2c23c9`)

`real_time/real_time_arbiter.py:419-431` now applies a `CAPTURE` fate only when
`resolution_time <= self.clock`, re-deriving it each tick until the clock catches up:

```python
if kind is _CollisionOutcome.CAPTURE:
    if resolution_time > self.clock:
        continue          # not yet — re-derived next tick
```

Truncation still applies eagerly, which is correct: a piece needs to know where it is
stopping before it gets there, whereas a capture must not happen before the pieces meet.
`tests/test_collisions.py`'s `test_very_tiny_time_increment_no_collision` is no longer
`xfail` — the suite reports **0 xfailed**. Two rooks ordered across nine squares now die at
the square they meet on, not on the first 50 ms tick.

### 8.2 [S1] A king captured as the loser of an arrival race does not end the game — ✅ FIXED (`c6914ef`)

`_resolve_collision`'s losers loop no longer marks state inline. Every cross-colour loser
goes through `_destroy_in_transit(m, winner.move_id)`, which returns whether the destroyed
piece was a king, and the loop ORs that into `king_captured`:

```python
king_captured = self._destroy_in_transit(m, winner.move_id) or king_captured
```

`_capture_in_flight` (the path-collision route) delegates to the same helper, so the king
check exists in exactly one place for both routes.

### 8.3 [S1] A piece captured at its origin leaves a "ghost" move — ✅ FIXED (`e0c7d70`)

Two changes, together:

* `Board.move_piece` no longer sets `State.captured` at all. Its docstring now says so
  explicitly and names `RealTimeArbiter._mark_captured` as the owner.
* `_mark_captured(piece, capturing_move_id)` is idempotent, publishes `PieceCaptured`, and
  calls `_drop_moves_for(piece)` — so a corpse's `Move` leaves `pending_moves` immediately
  and can never again truncate, block, or capture. The score double-count and the phantom
  blocker both follow from this one fix.

The related occupancy hole (a mover's origin square being permanently occupied by a piece
that has already left) was closed at the same time by `_vacate_departed_origins`, with
`_retreat_vacated_move` handling a move that can no longer complete: it walks backward along
its own path to the nearest free square rather than teleporting home.

### 8.4 [S1] Out-of-range coordinates from the wire crash the connection *and* leak the game — ✅ FIXED (`c2c23c9`)

Three independent layers now, defence in depth:

1. `shared/messages.py:26-28` — `PositionPayload.x/y` are `Field(ge=0, lt=BOARD_SIZE)`. A
   malformed frame fails pydantic validation and returns an `ERROR` envelope. This also
   closes the negative-index wrap-around, which was the worse half of the bug: `Position(-1,
   -1)` used to silently address the white rook.
2. `rules/rules_engine.py:49-51` — the commented-out bounds check is restored, returning the
   new `MoveReason.OUT_OF_BOUNDS`. The engine is safe even if called from the local GUI or
   the textTester.
3. `server/main.py:69-87` — the receive loop has `except WebSocketDisconnect`, a catch-all
   `except Exception` that logs, and a `finally` that always runs `manager.remove` and
   `_handle_disconnect`. No exception can strand a username in `logged_in_usernames` or
   leave a `GameSession` ticking with no reader any more.

### 8.5 [S2] Head-on ties annihilate both pieces; two kings produce two contradictory winners — ✅ FIXED (`13cc05e`)

`_resolve_path_collisions:379-411` picks a single loser on an exact tie by `move_id` — the
piece ordered first survives, matching the "earlier starter wins" intent the tests already
expressed:

```python
loser, loser_path = (b, path_b) if a.move_id < b.move_id else (a, path_a)
```

Both the same-colour (double-truncation) and cross-colour (mutual annihilation) branches now
resolve exactly one move, so a king-vs-king tie publishes one `GameEnded` with one winner,
and the Elo write is no longer decided by list iteration order.

### 8.6 [S1] A failed Elo job kills the entire `GAME_OVER` pipeline, permanently — ✅ FIXED (`13cc05e`)

`server/game_session.py:255-258`:

```python
try:
    ratings = await asyncio.wrap_future(self._elo_future)
except Exception:
    logger.exception("Elo update failed for game %s", self.id)
```

`GAME_OVER` now ships with empty `rating_changes` if persistence failed, `on_finalize` still
runs, and registry/room entries no longer leak. Telling the players the game ended is
correctly treated as more important than the rating write.

### 8.7 / 8.8 / 8.9 [S2] Session-lifecycle leaks around observers — ✅ FIXED (`13cc05e`)

All three shared one root cause: only players were ever removed from room state.

* `server/handlers.py:82-89` — `_on_game_finalized` iterates
  `(*game.players.values(), *game.observers)`. A spectator is no longer wedged in
  `_player_to_room`, so their next `play` / `room` is accepted (§8.7).
* Because the last occupant now leaves, `RoomManager.leave` reaches `close_room` and the
  room — along with its stale `game_id` — disappears instead of poisoning that id forever
  (§8.8).
* `server/main.py:57-61` — the observer branch of `_handle_disconnect` calls
  `handlers.room_manager.leave(session)` alongside `remove_observer` /
  `remove_player_mapping`, with a docstring explaining why (§8.9).

### 8.10 [S2] `handle_play` crashes on a user with no rating row — ✅ FIXED (`13cc05e`)

`server/handlers.py:277-281` awaits the rating and checks it before it can reach
`abs(seeker.rating - rating)`:

```python
if rating is None:
    await conn.send_error(ERROR_ACCOUNT_NOT_FOUND)
    return
```

The optimistic comment ("logged-in players always have a user row") is gone.

### 8.11 [S2] `broadcast_state` and `_finalize` abort on the first dead recipient — ✅ FIXED (`13cc05e`)

All three fan-out sites (`broadcast_state`, `_broadcast_event`, `_finalize`) use:

```python
await asyncio.gather(
    *(session.connection.send(envelope) for session in self._recipients()),
    return_exceptions=True,
)
```

One flaky spectator can no longer starve the players behind them in the list.

### 8.12 [S3] `MoveLog._pending_captures` grows without bound — ⬜ OPEN

`game_engine/move_log.py:38-40` adds every `capturing_move_id` to a set, and only
`_on_move_completed` discards. A capturing move that is later **truncated or aborted** never
publishes `MoveCompleted`, so its id stays forever. Small, but unbounded for the life of a
game.

**Fix shape:** also subscribe to `MoveTruncated` / `MoveAborted` and discard there. Both
events carry `move_id`, so this is three lines.

### 8.13 [S4] `_release_expired_rests` silently drops entries for non-resting pieces — ⬜ OPEN (downgraded)

`real_time_arbiter.py:238-239` — `if not entry.piece.state.is_resting(): continue` drops the
entry without adding it to `still_resting`. This is now *documented* as intentional (the
docstring says "pieces captured while resting are dropped, never resurrected") and is safe
in practice because §8.3 made `_mark_captured` the only writer of `State.captured`. What
remains is that any *other* unexpected state change is discarded with no diagnostic —
a smell rather than a defect. Downgraded from S3 to S4.

### 8.14 [S3] `Position.__eq__` raises on a non-`Position` — ⬜ OPEN

`model/position.py:8-9` — `value.x` assumes the operand is a `Position`. **[verified]**
`Position(0,0) == None` → `AttributeError: 'NoneType' object has no attribute 'x'`.

Removing `EMPTY_CELL` narrowed the blast radius (there is no longer a `str` in the grid to
be compared against a position), but board cells are now `Piece | None`, so comparing a cell
to a position raises instead of returning `False`. Should return `NotImplemented` for
unknown types — a two-line fix that lets Python fall back to identity comparison.

---

## 9. Protocol & feature gaps

### 9.1 [S2] Six of fourteen `MessageType`s have no handler — ✅ FIXED (`445074d`, `648c025`)

`MessageType` is now fourteen live members with no vestigial ones:

```
register     handler        state        server→client
login        handler        game_start   server→client
move         handler        game_over    server→client
jump         handler        event        server→client
create_room  handler        error        server→client
join_room    handler
play         handler
resign       handler   ← new
cancel_seek  handler   ← new
```

`CHAT` and `AUTH` (with `AuthPayload`) were **deleted** rather than left as scaffolding.
`RESIGN` is implemented end to end: `handle_resign` → `finalize_by_forfeit(opponent, "resigned")`,
`RemoteGame.resign()` on the client, and `KEY_RESIGN` (`r`) in `GameLoop`. **A player can
now concede without killing the connection.**

### 9.2 [S2] `play` never acknowledges a queued seek — ✅ FIXED (`445074d`)

`handle_play` sends an explicit `PLAY` envelope back when no opponent is found, and stores
the timeout handle in `_pending_seek_timers`. `CANCEL_SEEK` cancels both the timer and the
pool entry and echoes back, so a client that gives up no longer strands itself in the seek
pool.

### 9.3 [S2] No logout, and login is per-connection only — ⬜ OPEN

`logged_in_usernames` is added to in `handle_login` and discarded **only** in
`_handle_disconnect`. There is still no `LOGOUT` message and no way to switch accounts
without reconnecting.

The severity is materially lower than it was: §8.4's `finally` means the discard is now
guaranteed to run on *any* socket exit, so a username can no longer be stranded for the
process lifetime by a crash. What remains is a missing feature, not a leak.

### 9.4 [S2] Networked play has no move or capture sounds — ✅ FIXED (`445074d`)

The `EVENT` message type carries `EventPayload(event_type, data)` for every member of
`FORWARDED_EVENTS` (`STATE_CHANGING_EVENTS` minus `GameEnded`, which `GAME_OVER` already
carries). `server/encoding.py` encodes the arbiter's dataclasses; `client/remote_game.py`
decodes them back into the real `events/` types and republishes them on the local bus, so
`SoundPlayer` — and any future client-side move log or capture animation — works online
with no changes.

The design note worth keeping: a coalesced `STATE` diff is the right shape for *rendering*
and the wrong shape for *cues*. The two channels exist because they answer different
questions ("what does the board look like" vs "what just happened").

Note this fix is currently unobservable in practice for a different reason — see §13:
`view/assets/sounds/` does not exist, so every sound logs "asset missing" in local play too.

### 9.5 [S2] The GUI never closes itself when the game ends — ✅ FIXED (`445074d`)

`view/game_loop.py:_should_exit` returns True on `not self.game.game_active and not
self.scene_animator.is_active()`, so the victory overlay plays to completion and then the
window closes itself, returning control to `Shell._enter_game` to print the result and
rating change. Covered by `tests/test_game_loop.py`.

---

## 10. Architectural problems

### 10.1 `view` ↔ `input` is a circular package dependency — ✅ FIXED (`648c025`)

`input/board_mapper.py:1` now reads `from shared.protocol_config import DEFAULT_BOARD_SIZE`.
`input/` imports nothing from `view/`; the cycle is gone. `view/` → `input/` remains, which
is the direction `GUI_runner` actually needs.

### 10.2 `client/` depends on `view/` for domain constants — ✅ FIXED (`648c025`)

`DEFAULT_BOARD_SIZE` and `MS_PER_SECOND` moved to `shared/protocol_config.py`, with
`DEFAULT_BOARD_SIZE` re-exporting `model.board.BOARD_SIZE` so there is still exactly one
definition. `client/remote_game.py` imports them from `shared/`; `view/view_config.py` now
imports them from `shared/` too rather than declaring them. A headless client no longer
pulls in the rendering config.

### 10.3 `Board` performs game logic it shouldn't own — ✅ FIXED (`648c025`)

`move_piece` no longer marks captures (the arbiter's `_mark_captured` does) and no longer
promotes (`rules/promotion.py::is_promotion_square` is a pure predicate the arbiter applies).
`place_piece` is a thin `set_piece_at`. `model/` is once again dumb state, and the
cross-layer silence that caused §8.3 is closed structurally, not just patched.

### 10.4 Ownership is not an engine concept — ⬜ OPEN

* the **arbiter** enforces the in-flight/rest lock (`piece.state != State.idle`);
* the **engine facade** re-checks `is_resting()` before delegating;
* the **server handler** enforces piece ownership via `piece_color_at`.

The engine itself still has **no concept of ownership** — **[verified]** `game.jump_request`
on an enemy pawn returns `MoveValidation(is_valid=True, reason=MoveReason.OK)`. That is
intentional for local hot-seat play, but it means the *only* thing standing between a
malicious client and moving its opponent's pieces is one `if` in `handle_move` / `handle_jump`.

The previous revision's related complaint — that those handlers reached into
`game.engine.board` — is resolved: they use `engine.piece_color_at` now, so the layering
violation is gone even though the ownership concept still lives server-side. Promoting it
to `move_request(color, origin, target)` remains the cleaner design.

### 10.5 `_resolve_collision` is a defensive fallback that is nearly unreachable — ⬜ OPEN (downgraded to S4)

Because a move's target is always in its own path, two moves to the same square are normally
caught by `_resolve_path_collisions` first. `_resolve_collision` is therefore reached only
via the airborne `continue` branches and same-tick edge cases. The dangerous half of this
finding is gone — it no longer misses the king check (§8.2) — so what remains is dead-ish
code with an honest comment. Worth either deleting with a proof that the path is
unreachable, or keeping and testing directly.

### 10.6 Global mutable singletons in `server/handlers.py` — ⬜ OPEN

`registry`, `room_manager`, `clock`, `persistence`, `logged_in_usernames` and now
`_pending_seek_timers` are module-level and resolved at call time. Tests must monkey-patch
them (`handlers.registry = GameRegistry()`), which the suite does via an autouse fixture. It
works, but it makes multi-tenancy impossible, makes handler unit tests order-sensitive, and
means `import from` (rather than attribute access) silently breaks. An `AppContext` passed
through `dispatch` would cost little.

### 10.7 `PlayerSession.__init__` mutates its argument — ⬜ OPEN

`server/session.py:7` — `connection.player_session = self`. A constructor with a hidden side
effect on a collaborator; `handle_login` relies on it (`PlayerSession(username, conn)` with
the result discarded), which reads as a no-op statement.

### 10.8 O(n²) full-path recomputation every tick — ⬜ OPEN

`_resolve_path_collisions` recomputes `_path_cells` for both members of every pair on every
`advance_time` — and the §8.1 fix means a not-yet-due capture pair is now re-derived on
*every* tick until its resolution time arrives, so the constant went up slightly. Fine at
this scale, but it is recomputing immutable data (a move's path never changes except on
truncation). Cache the path on the `Move`.

### 10.9 Asset config duplicates engine logic that is never read — ⬜ OPEN

`view/assets/pieces/*/states/*/config.json` carries `physics.speed_m_per_sec` and
`physics.next_state_when_finished` — e.g. `move` declares `1.5` m/s and
`next_state_when_finished: "long_rest"`. **Nothing reads `physics`.** Speed is
`DEFAULT_MOVE_DELAY_MS` and the transition is `RealTimeArbiter._begin_rest`. Two
contradictory sources of truth, one of them silently ignored.

---

## 11. Inconsistencies

### 11.1 `EMPTY_CELL = '.'` — a string sentinel in a grid of objects — ✅ FIXED (`648c025`)

The single most pervasive design weakness in the previous revision is gone. Cells are
`Piece | None`; `get_piece_at` returns `Optional[Piece]`; `is_cell_empty` is an `is None`
check. `RemoteBoardView.get_piece_at` returns `Optional[PieceDTO]` rather than imitating a
sentinel it no longer needs to. The `'.'` token survives only as
`tester_config.EMPTY_TOKEN`, explicitly documented as a DSL symbol distinct from the domain
representation.

### 11.2 `MoveValidation.reason` is typed `str` but is always a `MoveReason` — ⬜ OPEN

`rules/rules_engine.py:20-23`. The whole point of introducing the StrEnum was to kill bare
strings; the type hint still invites them. Same in `client/remote_game.py:66-70`
(`RemoteMoveResult.reason: str`). `game_engine/payloads.py`, the third instance, was
deleted.

### 11.3 The client re-declares reason strings the enum already owns — ⬜ OPEN

`client/remote_game.py:52-53`:

```python
OBSERVER_CANNOT_MOVE_REASON = "observer_cannot_move"
MOVE_OK_REASON = "ok"
```

`"ok"` is `MoveReason.OK`. The comment justifying not importing `rules/` is fair — the
client must not depend on the rules layer — but the answer is to put the shared vocabulary
in `shared/protocol_config.py`, not to keep a third private copy of `"ok"`.

### 11.4 `"print_score"` is a bare magic string in two files — ⬜ OPEN

`textTester/parser.py:126` emits `("print_score",)` and `script_runner.py:37` keys on
`"print_score"`, while every sibling command uses a `tester_config` constant
(`CMD_CLICK`, `CMD_JUMP`, `CMD_WAIT`, `CMD_PRINT`, `PRINT_ARG_SCORE`). Directly against the
project's own "no magic values" rule, and the constant it should use already exists.

### 11.5 `validate_move` is a module function indented like a method — ⬜ OPEN (partly)

`rules/rules_engine.py:34-60` — both `validate_piece_move` and `validate_move` have
8-space-indented bodies, a leftover from when they were class methods. One improvement: the
commented-out bounds check is now *live* code (§8.4). One commented-out block remains:

```python
# if board.is_friendly(destination, piece.color):
#     return MoveValidation(False, "friendly_destination")
```

— which also contains the last bare reason string in the rules layer.

### 11.6 `Move` is a plain class while everything around it is a dataclass — ⬜ OPEN

`real_time_arbiter.py:32-39`. `RestingPiece` directly below it *is* a dataclass. The project
rule says dataclasses for all new code. (`Move` is mutated in place by `_truncate_move`, so
it wants a non-frozen dataclass, not a frozen one.)

### 11.7 `Piece.__init__` takes raw strings and shadows `type` — ⬜ OPEN

`model/piece.py:24-29` — `Piece(id_num, color: str, type: str, position)` converts internally
via `Color(color)` / `PieceType(type)`. `Board.generate_standard_grid` then passes
`color.value` / `p_type.value` — an enum → str → enum round trip for no reason. `type` also
shadows the builtin.

### 11.8 Three `from X import *` star-imports — ⬜ OPEN (was four)

`real_time/real_time_arbiter.py:9`, `view/game_loop.py:4`, `view/renderer.py:4`.
`input/board_mapper.py` was fixed as part of breaking the §10.1 cycle — which is itself the
argument against the remaining three: a star-import is what let that cycle hide. They still
make `DEFAULT_MOVE_DELAY_MS`'s origin invisible at the arbiter's call sites.

### 11.9 CLAUDE.md is stale — ✅ FIXED (2026-07-29)

CLAUDE.md survived `648c025` describing code that commit had just deleted. Corrected, along
with everything else that had drifted since the `c2769b8` baseline:

* the `EMPTY_CELL` sentinel (twice — the `model/` bullet and the test-authoring guidance,
  which told authors to write `Board([[EMPTY_CELL]*8 ...])`), and the claim that
  `move_piece`/`place_piece` apply promotion;
* the `handle_move` "reaches into `game.engine.board`, flagged with a `TODO`" gotcha —
  replaced with the accurate and still-load-bearing warning that the *engine* has no
  ownership concept, so `piece_color_at` in the handlers is the only thing enforcing it;
* `ScoreChanged`, `MessageType.chat`/`auth`, and "there is no requirements.txt";
* the arbiter bullet, which predated the collision-timing gate, the `move_id` tie-break,
  `_vacate_departed_origins` and single-sourced king checks;
* `RESIGN` / `CANCEL_SEEK` / the `EVENT` channel, the guarded receive loop, `gather`-based
  fan-out, observer room cleanup, and `GameLoop`'s self-exit;
* the test count (496 → 546, xfail gone).

`tests/conftest.py`'s docstring — which claimed `EventBus` is `asyncio.Queue`-backed — was
corrected in the same pass, so CLAUDE.md no longer has to carry an erratum about it.

Two gotchas were **added**, both being things that cost real debugging time: that a new event
type must be registered in four places (`STATE_CHANGING_EVENTS`, `FORWARDED_EVENTS`, the
encoder table, the decoder table), and that the missing asset directories (§13) mean
`SoundPlayer` and `SceneAnimator` produce nothing at runtime despite being fully implemented.

### 11.10 Hebrew comments/docstrings remain in six places — **[verified]** — ⬜ OPEN

`input/board_mapper.py:7`, `model/game_snapshot.py:6`, `view/assets/asset_manager.py:110`,
`tests/ultra_tests.py:220,393,396`. The rest of the codebase is documented in English.
(Unchanged in count — `board_mapper.py:14`'s Hebrew went with the deleted `logic_to_pixels`,
but the file still has one on line 7.)

---

## 12. Code smells

| # | Where | Smell | Status |
|---|---|---|---|
| 12.1 | `view/assets/asset_manager.py:19-21` | `import os` *inside* a method, plus `print("Files Python sees in assets:", …)` — a debug print in the load path of every run | open |
| 12.2 | `server/main.py:87` | `print(f"{conn.id} disconnected")` in the `finally` — and the file now *has* a configured `logger` two lines away that it uses for the exception path | open |
| 12.3 | `view/assets/asset_manager.py:7` | `def __init__(self, base_path="assets")` — the parameter is immediately overwritten by `Path(__file__).parent` and never used | open |
| 12.4 | `view/GUI_runner.py:16` | `sound_player = SoundPlayer(...)` assigned and never referenced; it works only via its constructor's subscription side effect. Same shape as §10.7 | open |
| 12.5 | `input/controller.py:8` | `self.pos` is a per-call temporary promoted to instance state by `update_position`; two clicks in flight would alias | open |
| 12.6 | `game_engine/game.py:17` | the parameter is named `initial_board` but takes a **grid** (list of lists), which is then wrapped in `Board(...)`; `Board.generate_standard_grid()` likewise returns a grid, not a board | open |
| 12.7 | `model/board.py:38-41` | `Board.__init__` accepts any list of lists — **[verified]** a 3×3 grid is accepted silently (`rows=3, cols=3`), and `cols` is read from row 0 only, so a jagged grid passes too | open |
| 12.8 | `game_engine/move_log.py:51` | `timestamp_ms=time.time() * 1000` — wall-clock time in a log whose every other field is game-clock derived. Replaying a log cannot reconstruct timing | open |
| 12.9 | `events/event_bus.py:9` | `#TODO: change to async` — stale; the sync design is deliberate and documented at length in `game_session.py` and here | open |
| 12.10 | `textTester/parser.py:122-126` | `print` with a missing argument raises `IndexError`; an unrecognised one is silently dropped, with no error message | open |
| 12.11 | `textTester/parser.py:57-77` | `is_valid_board` checks row-width consistency but never that the board is 8×8; a 3×3 grid builds a `Board` the renderer and `PawnRules.START_ROW` will misinterpret (see §12.7) | open |
| 12.12 | `real_time_arbiter.py:168-170` | a commented-out up-front `validate_move` in `add_move`, with a four-line comment explaining why it *should* be there | open |
| 12.13 | `tests/test_e2e.py:29` | `controller_module.selected_piece_pos = None` sets a module attribute that does not exist (it's an instance field) — a no-op left over from a module-level controller | open |
| 12.14 | `game_engine/snapshot.py:34-58` | `get_all_pieces` scans all 64 cells on every call; the GUI calls it ~30×/sec | open |
| 12.15 | `server/rooms.py:50-56` | `leave` still returns a `LeaveResult` **no caller reads** — both call sites discard it. It was trimmed from five fields to two, so the waste is smaller, but the documented "opponent left" notification was never built | open (reduced) |
| 12.16 | `game_engine/score_tracker.py` | re-entrant `ScoreChanged` publication from inside a `PieceCaptured` handler | ✅ **fixed** — `ScoreChanged` deleted; the tracker only tallies |

---

## 13. Dead code

Ten of the thirteen entries in the previous revision were removed in `648c025` / `445074d`.

| Symbol | Status |
|---|---|
| `ScoreChanged` | ✅ deleted from `events/game_events.py`; `ScoreTracker` no longer publishes |
| `MessageType.RESIGN` / `ResignPayload` | ✅ implemented end to end (§9.1) |
| `MessageType.CHAT` | ✅ deleted |
| `MessageType.AUTH` / `AuthPayload` | ✅ deleted |
| `MoveValidationPayload` / `game_engine/payloads.py` | ✅ module deleted, with its test |
| `DISCONNECT_REASON` | ✅ now `GAME_OVER_REASON_DISCONNECT`, read by `main.py` |
| `SQUARE_SIZE`, `WAIT_TICK_INTERVAL_SECONDS` | ✅ deleted from `view/view_config.py` |
| `BoardMapper.logic_to_pixels` | ✅ deleted |
| `Img.fill_rect` | ✅ deleted |
| `ConnectionManager.get` | ✅ deleted |
| `LeaveResult.role` / `remaining_players` / `remaining_observers` | ✅ deleted (the object itself is still unread — §12.15) |
| **`view/assets/sounds/`** | ⬜ **the directory does not exist.** `SOUND_ASSET_MAP` names four `.wav` files; `SoundPlayer` logs "asset missing" and skips for every event, in local *and* networked play. The §9.4 `EVENT`-channel fix is therefore correct but currently silent |
| **`view/assets/scenes/intro/`, `scenes/victory/`** | ⬜ **neither directory exists** — no `config.json`, no `sprites/`. `SceneAnimator` is fully implemented, now unit-tested (`tests/test_scene_animator.py`) and load-bearing for `GameLoop`'s exit condition (§9.5), and still draws nothing |

The two remaining entries changed character: they are no longer *unused code*, they are
**implemented features with no assets**. Shipping four `.wav` files and two sprite folders
would light up the sound system, the intro/victory overlays, and the polish half of §9.5 at
once — the highest visible-payoff-per-effort item left in the repo.

---

## 14. Testing, ops & hygiene

### 14.1 Coverage gaps

The suite grew 485 → 546 and is deterministic by construction (no sleeps, faked clock, faked
persistence). Three of the five gaps in the previous revision are closed:

* ✅ **`server/main.py` is now tested** — `tests/test_main.py` (141 lines) covers the
  websocket endpoint and its disconnect paths, the file where §8.4/§8.7/§8.9 all lived.
* ✅ **`view/` has its first coverage** — `tests/test_game_loop.py` and
  `tests/test_scene_animator.py`. `GameRenderer`, `PieceAnimator`, `SoundPlayer`,
  `AssetManager` and `Img` remain untested.
* ✅ **`client/network.py` is tested** — `tests/test_client_network.py`.
* ✅ **The invariants that were untested are now tested** — `test_real_time_arbiter.py` and
  `test_collisions.py` grew by 290 lines between them covering pending-move eviction, king
  capture in an arrival race, and single-winner ties.
* ⬜ **`client/shell.py` is still untested** — the entire REPL and its `wait_for` timeout
  choreography, including the new `cancel_seek` path.
* ⬜ **`server/async_clock.py` is still untested** — always faked, never itself verified.
  Note `_pending_seek_timers` (new in `445074d`) depends on `TimerHandle.cancel` actually
  working, which nothing asserts.

### 14.2 Repository hygiene — ✅ MOSTLY FIXED

* ✅ The tracked `.pyc` is gone — `git ls-files | grep pycache` returns nothing.
* ✅ `.gitignore` is five lines and now covers `__pycache__/`, `*.pyc`, `*.db`, `.venv/` and
  `.pytest_cache/`. The SQLite file with usernames, salts and scrypt hashes can no longer be
  swept up by `git add .`.
* ✅ `requirements.txt` exists, listing pytest, opencv-python, numpy, fastapi, uvicorn,
  pydantic and websockets.
* ⬜ Still no `pyproject.toml`, and `requirements.txt` pins no versions — reproducible
  installs are still not guaranteed.

### 14.3 Security & robustness

* **Good:** scrypt with per-user salt at `N=2^14`, constant-time compare, no username
  enumeration on login, hashing off the event loop, parameterised SQL everywhere.
* ✅ **Input bounds validation** — the highest-value item in the previous revision, closed
  three ways (§8.4).
* ✅ **Unhandled exceptions no longer strand state** — the `try/except/finally` in
  `websocket_endpoint` (§8.4) means an account can't be locked out and a game can't leak by
  way of a crash.
* ⬜ **No rate limiting** on any message. A client can flood `MOVE` and get an `ERROR` frame
  per attempt. `CANCEL_SEEK`/`PLAY` can be cycled freely too.
* ⬜ **No frame size limit** — `websocket.receive_text()` is unbounded, and
  `Envelope.payload: dict[str, Any]` accepts arbitrary nesting. `EventPayload.data` is
  likewise a free-form dict (server→client only, so not an inbound risk).
* ⬜ `Envelope.model_validate_json` errors are echoed back verbatim with `str(exc)`, leaking
  pydantic's internal schema details to the client. This now includes the new
  `PositionPayload` bounds constraints.
* ⬜ `/debug/connections` is unauthenticated (it returns only a count).
* ⬜ `ServerConnection._connect_and_receive` (client) has no reconnect: a `ValidationError`
  on an inbound frame, or a server-side close, ends the network thread while the main thread
  keeps waiting.
* ⬜ `ServerConnection.send` dereferences `self._ws` without a None check — if `start()`'s
  10-second connect times out, the first send raises `AttributeError`.

---

## 15. Suggested order of work

Tiers 1 and 2 of the previous revision are **complete**. What remains, ranked by
(damage × likelihood) ÷ effort:

**Tier 1 — visible payoff, low effort**

1. **§13** Ship the missing assets: four `.wav` files under `view/assets/sounds/` and
   `config.json` + `sprites/` under `scenes/intro/` and `scenes/victory/`. Three fully
   implemented, now-tested subsystems (`SoundPlayer`, `SceneAnimator`, and the `EVENT`
   channel that exists to feed them) currently produce nothing.
2. **§8.12** Discard `_pending_captures` entries on `MoveTruncated` / `MoveAborted` — three
   lines, closes the last unbounded-growth path in the engine.
3. **§8.14** Return `NotImplemented` from `Position.__eq__` for unknown types.
4. ~~**§11.9** Correct the stale CLAUDE.md claims.~~ ✅ done 2026-07-29 — stale guidance in
   the file that *instructs future work* is worse than stale prose in a review document.

**Tier 2 — correctness at the edges**

5. **§10.4** Make colour ownership a first-class engine concept
   (`move_request(color, origin, target)`), so a client can't move enemy pieces if one
   server-side `if` is ever missed.
6. **§14.1** Test `client/shell.py` and `server/async_clock.py` — the new
   `_pending_seek_timers` logic depends on `TimerHandle.cancel`, which nothing asserts.
7. **§12.7 / §12.11** Validate board dimensions in `Board.__init__` and the textTester
   parser. **[verified]** a 3×3 board is silently accepted today.
8. **§14.3** Frame size limit, basic rate limiting, and stop echoing raw pydantic errors.
9. **§9.3** Add `LOGOUT` so a user can switch accounts without reconnecting.

**Tier 3 — structure and hygiene**

10. **§11.2 / §11.3** Type `reason` as `MoveReason`; move the shared reason vocabulary the
    client needs into `shared/protocol_config.py`.
11. **§11.4** Replace the last `"print_score"` magic string with the existing constant.
12. **§11.8** Kill the three remaining star-imports — the fourth was what hid the §10.1
    cycle.
13. **§11.6 / §11.7** `Move` as a dataclass; `Piece.__init__` taking enums directly instead
    of round-tripping through strings.
14. **§10.8** Cache each `Move`'s path — the §8.1 fix made the recomputation slightly hotter.
15. **§10.6** An `AppContext` through `dispatch` instead of module-level singletons.
16. **§12.1 / §12.2** Remove the debug `print`s; route `server/main.py`'s disconnect notice
    through the `logger` it already has.
17. **§10.5** Either delete `_resolve_collision` with a proof it's unreachable, or test it
    directly.
18. **§10.9** Delete the unread `physics` block from the asset configs, or make it the
    source of truth for speed and rest transitions.
