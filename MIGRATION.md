# Upscaling CTD toward the Kung-Fu Chess server spec

## Context

`kung-fu-chess-server-spec-agent.md` describes a ~1.43M-concurrent-game system: eleven tiers, a
Go game engine, NATS, Redis, Postgres, spectator relays, Kubernetes. The repo today is a single
FastAPI process that ticks every game at 50 ms, broadcasts full board state as JSON, authenticates
with a plaintext password over the WebSocket, and forfeits a player the instant their socket drops.

The good news is that the load-bearing invariants are already true here. I4 (closed-form
`time_at_cell = start + (index+1) × DELAY`) is implemented at `real_time/real_time_arbiter.py:306`.
I5 (absolute times, never sampled progress) is on the wire at `shared/messages.py:103`. I3 (arbiter
is the only publisher) and I6 (coalescing via `_mark_dirty`) hold. I2's layering is intact. So this
is not a rewrite — it is a staged extraction, and every phase below is independently shippable.

Per your decisions this plan covers the **whole spec except the Go rewrite** — phases 0 through 8
below reach spectator relays, PG sharding, regions, and Kubernetes. Three deliberate departures,
all yours: **everything stays Python** (game tier and client alike — no Go engine, no TypeScript
client), and **binary wire format and replays stay out**, consistent with the spec's own §3 and
Appendix C. All three behavioural changes are in (pause/reconnect budget, matchmaking band
widening, 16-char room codes).

**What staying in Python costs, stated up front.** The spec's 20,000-games-per-node figure assumes
goroutine-per-shard with no GIL. A Python game node will land somewhere well below that, and the
honest answer is that phase 0's bench is what tells us where. The structural response is in phase 4:
**one Python process = one game node**, several nodes packed per machine, `hash(game_id) mod S`
choosing the node rather than a shard inside it. This keeps the spec's subject namespace
(`cmd.{shard}.{node_id}`) exactly as written, needs no IPC, and means lower density shows up as
more node processes rather than as a design change. Same story for the relay tier: Python asyncio
holds fewer sockets per instance than Go, so phase 5 scales out in instance count. Nothing in the
architecture bends; only the fleet size does.

### Where we stand against the spec

| Spec requirement | Today | Phase |
|---|---|---|
| I4 closed-form time | ✅ `_time_at_cell` | — |
| I5 absolute times on wire | ✅ `move_start_ms`/`move_arrival_ms` | — |
| I3 / I6 / I2 / I7 | ✅ | — |
| Delta encoding, keyframes, seq/resync | ❌ full 1.5 KB state per change | 1 |
| Discrete-event scheduler | ❌ 50 ms tick per game | 2 |
| Language-neutral schema | ❌ hand-written pydantic | 3 |
| Tier separation, NATS, Redis, PG | ❌ one process, sqlite | 4 |
| JWT / Ed25519 / scrypt N=2^13 | ❌ password over WS, sqlite scrypt | 4 |
| Pause-by-offset, 10 s budget | ❌ instant forfeit (`server/main.py:57`) | 2 |
| Band widening ±100→±400 | ❌ fixed ±100 (`server/rooms.py:152`) | 0 |
| 16-char room codes + claim FSM | ❌ 6 chars (`server/server_config.py:19`) | 0 / 4 |
| Instrumentation | ❌ none | 0 |
| Spectator relays, lazy `spec.*`/`kf.*` | ❌ observers fan out from the game itself | 5 |
| PG sharding, identity table, retention | ❌ one sqlite file | 6 |
| Regions | ❌ none | 7 |
| K8s, drain hooks, Prometheus, canaries | ❌ none | 8 |

---

## Phase 0 — Instrument, plus the cheap behavioural wins

Spec §17 says measurements (1) frames/s/game and (3) rebuild time can be taken on the existing
prototype *before* committing to the design. Everything in the capacity math is linear in the
assumed 3 frames/s/game, and nothing in this repo has ever measured it.

**Metrics.** New `observability/metrics.py`: a minimal counter/histogram registry with
cardinality discipline baked in — the recording API takes only a fixed label set, and `game_id` /
`user_id` / `session_id` are rejected outright (spec §12). No Prometheus dependency yet; a
`/metrics` text exposition endpoint is a ten-line addition when phase 4 needs it.

Instrument three places:
- `server/game_session.py` — frames emitted per game, bytes per encoded frame, events per frame
  (the coalescing ratio).
- `server/async_clock.py:34` — measure `elapsed_ms - tick_ms` as `drain_loop_lag_seconds`. This is
  spec §19's single most important internal metric and it costs one histogram observation.
- `real_time/real_time_arbiter.py` — scheduler events per move (validates the ~4/move estimate).

**Bench harness.** New `bench/frames_per_game.py`: drives N headless `KungFuChessGame` instances
through scripted move sequences via `wait()`, reporting frames/s/game, bytes/frame, and
`tracemalloc` bytes per live game. No server, no sockets, deterministic. These numbers are the
input to every phase-4 sizing decision.

**Behavioural wins** (self-contained, no dependencies):
- `server/rooms.py:152` `_find_opponent` — replace the fixed `MATCH_ELO_RANGE` with a widening
  band: ±100, +50 every 5 s, capped ±400. Needs the seeker's enqueue time, so `_Seeker` gains
  `queued_at_ms` and `seek` takes the clock. Constants to `server/server_config.py`.
- `server/server_config.py:19` — `ROOM_ID_LENGTH` 6 → 16 (~80 bits, spec's brute-force fix).
- `server/rooms.py` — add the one-way `waiting → live → ended` room state machine and the
  idempotent seat-2 claim (`seat2_uid == caller_uid` short-circuits a repeat join). In a
  single-threaded `RoomManager` the claim is trivially atomic; phase 4 swaps the same predicate
  for Redis `HSETNX` without changing the caller. Also encodes spec §7's hard invariant: **a
  spectator is never promoted to a player.**

---

## Phase 1 — Delta protocol, keyframes, sequence numbers, resync

The single highest-leverage change: 1.5 KB → ~150 B per frame, which is the difference between
360 Gbps and 36 Gbps at target scale.

**Deltas are built from the event stream, not from diffing snapshots.** This falls out of I3 —
the arbiter already publishes an event for every state change, which is exactly why CLAUDE.md
warns that a mutation without an event is invisible to clients. Each event maps to one spec §11
op:

| Event | Op |
|---|---|
| `MoveStarted` / `MoveTruncated` / `MoveAborted` | `m` (piece, from, to, t0, t1) |
| `PieceCaptured` | `x` |
| `RestEnded` | `r` |
| `ScoreTracker` change | `sc` |
| `GameEnded` | `end` |

New `server/delta.py`: a `DeltaBuilder` subscribing to the same `STATE_CHANGING_EVENTS` tuple,
accumulating positional-array ops into a buffer that `GameSession` drains once per pass into a
single frame (I6 preserved structurally).

**This collapses the `EVENT` channel into the delta stream.** Today `FORWARDED_EVENTS`
(`server/game_session.py:74`) fans out a second envelope per event purely so the client's
`SoundPlayer` gets per-event cues. A delta op *is* that cue — same information, one frame instead
of two. `MessageType.EVENT`, `_on_forwarded_event`, `_broadcast_event`, `server/encoding.py`'s
`_EVENT_ENCODERS`, and `client/remote_game.py`'s decoder table all go away, replaced by one
op→event decoder on the client that republishes onto the local bus. Net deletion.

**Envelope changes.** `shared/protocol.py`'s `Envelope` gains `seq`, `session_id`, `client_ts` —
at *envelope* level, not payload, so the phase-4 edge can gap-detect and route without ever
parsing a payload (I1 made structural). `MessageType.STATE` is replaced by `KEYFRAME` (full state,
today's `StatePayload` plus `seq` and `phase`) and `DELTA`; a new client→server `RESYNC` requests
a keyframe.

**Keyframe is the universal recovery path** (spec §10) — game start, observer join, reconnect,
client-detected seq gap, and later node rebuild all terminate in the same code path.

**Drop the heartbeat.** `MAX_STATE_INTERVAL_MS` (`server/server_config.py:34`) exists because a
dropped frame currently self-heals only by waiting a second. With seq-gap detection plus RESYNC it
is redundant, and spec §11 requires idle games to send zero frames. Liveness becomes WS ping/pong
only. Add the 1 frame/game/10 ms safety cap in `GameSession`.

**Client lockstep.** `client/remote_game.py`'s `RemoteGameState` is currently a frozen
whole-frame replacement; it becomes a keyframe-seeded state that applies delta ops in place.
`client/network.py:62` `_route` tracks last-seen `seq` and sends `RESYNC` on a gap; the
`_pending_state` hold-and-replay logic keeps working, now holding a keyframe. `view/` and `input/`
are untouched — `RemoteGameState.get_all_pieces()` keeps recomputing `progress` from absolute
times, so rendering is unaffected.

---

## Phase 2 — Discrete-event scheduler, and pause-by-offset

**`advance_time(ms)` stays as the public API.** Spec §18.2 requires the existing deterministic
tests to pass *unchanged*, and that is the acceptance criterion for this phase.

Inside `RealTimeArbiter`, replace the every-tick sweep with a per-game event heap ordered by
`(game_time, monotonic_seq)` — spec §5's determinism rule. Event kinds: `CELL_ENTER`, `MOVE_DONE`,
`REST_END`, `COLLISION`. `advance_time(ms)` becomes: pop events with `time <= clock + ms`,
advancing `self.clock` to each event's time as it is handled, then set `clock` to the target.
`_release_expired_rests` and `_pop_arrived_moves` disappear into heap entries.

**The risk is `_resolve_path_collisions` (`real_time_arbiter.py:313`).** It is an O(n²) all-pairs
sweep re-run every tick; the event model must compute fates at *schedule* time instead. Because
I4 is closed-form this is exact: when a move is enqueued, scan the (typically ≤4) other in-flight
moves, compute the shared-cell crossing times, and schedule a `COLLISION` event at
`resolution_time`. The existing semantics must be preserved exactly — earliest fate wins, ties
broken by lower `move_id`, truncation applied eagerly while capture waits for the clock, airborne
pieces intercepting through their jump window. Adding a move or truncating one invalidates
existing fates, so both re-run the scan for affected moves.

**Mitigation, and it is not optional:** keep the current implementation behind a flag and add
`tests/test_scheduler_equivalence.py` — a randomized differential harness that drives both
implementations over the same scripted move sequences and asserts identical event streams and
final boards. This is the same technique spec §18.5 uses for the Go rewrite, available here for
almost nothing, and it is what makes this refactor safe.

**`GameShard`.** New `server/game_shard.py`: one asyncio task owning many games with a per-shard
outer heap keyed on each game's next event time, replacing today's one-`asyncio.sleep(0.05)`-task-
per-game (`server/async_clock.py:34`, `GameRegistry.create_game`). This is the abstraction that
makes 20,000 games/node possible and it is a prerequisite for phase 4's game node, so it belongs
here rather than later. `AsyncClock` gains `at(time_ms, cb)` alongside `every`/`after`.

**Pause-by-offset.** `wall_time = game_time + pause_offset_ms`. With a heap, pause means stop
draining and record `paused_at`; resume adds elapsed to `pause_offset_ms`, re-keys the outer heap
entry, and emits a keyframe. On top of that:
- `GameSession` tracks a **10,000 ms budget per player per game** (total, not per pause — spec
  §11 closes the cable-yank griefing vector). Exhausted budget → forfeit through the existing
  `finalize_by_forfeit`, so the Elo/finalize gates are untouched.
- `server/main.py:45` `_handle_disconnect` stops forfeiting players immediately and pauses
  instead. Observers keep today's detach-and-leave path.
- Reconnect needs the returning socket re-bound to its game: a `resume_token` on `GAME_START`
  and a new `RESUME` message type. Phase 4 replaces the token with the JWT session id, so keep
  the lookup behind one function.

---

## Phase 3 — Language-neutral wire schema

`shared/` becomes generated rather than hand-written, so the Go engine and TS client can be
compiled from the same source later without I2 drifting.

- `schema/protocol.schema.json` as the source of truth. `PositionPayload`'s existing bounds
  (`ge=0, lt=BOARD_SIZE`) express directly as `minimum`/`exclusiveMaximum`, so the wire keeps
  refusing off-board coordinates before they reach a grid index.
- `tools/gen_protocol.py` regenerates `shared/messages.py` (datamodel-code-generator).
- `tests/test_schema_drift.py` regenerates into a temp dir and fails if the committed output
  differs — the CI guard that keeps the schema authoritative.
- Handshake version negotiation: `HELLO` / `HELLO_ACK` carrying a major `protocol_version`;
  additive-only within a major, unknown fields and opcodes ignored rather than errored.

---

## Phase 4 — Tier separation

The largest phase — roughly as much work as 0–3 combined. Seven services under `services/`,
NATS + Redis + Postgres, all Python; the game tier stays Python (Go is spec phase 5, out of scope
here).

| Service | Extracted from | Responsibility |
|---|---|---|
| `services/api_gateway/` | `server/handlers.py` | REST: register, login, refresh, profile, `POST /v1/rooms`, `/rooms/{code}/join`, `/v1/queue` |
| `services/auth/` | `server/persistence/password_hashing.py` | scrypt N=2^13 r=8 p=1, Ed25519 JWT (access 15 min / refresh 30 d rotated with reuse detection), JWKS |
| `services/edge/` | `server/main.py`, `connection.py` | WS sockets only; JWT verify vs cached JWKS, token bucket 10/s burst 20, **envelope parse only**, publish `cmd.{shard}.{node_id}`, subscribe `edge.{edge_id}` |
| `services/matchmaker/` | `server/rooms.py` seek pool | in-memory queues sharded by (region, rating bucket) |
| `services/allocator/` | `server/rooms.py`, `game_registry.py` | placement, directory `game:{id}`, node lease 3 s TTL renewed at 1 s, room lobbies `room:{code}` via `HSETNX` |
| `services/game_node/` | `game_session.py`, `game_shard.py` | the only tier importing `game_engine`/`real_time`/`rules`; batched log append to Redis `log:{game_id}` |
| `services/result_writer/` | `server/elo.py`, `user_repository.py` | consumes `evt.result`, batches, one PG transaction, `ON CONFLICT DO NOTHING` as idempotency key |

**The one design decision that makes this survivable: a bus abstraction with two adapters.**
`bus/` defines publish/subscribe over the spec's subject namespace; `bus/nats_adapter.py` is
production, `bus/inprocess_adapter.py` runs every service in one process against one virtual
clock. Without this, phase 4 destroys I7 — the entire existing test suite depends on being able
to fire clock callbacks by hand. With it, multi-tier tests stay deterministic and sleep-free, and
`main.py`'s local single-process game keeps working.

**Edge rules that must not be violated** (spec §4): the edge never dials a game node and holds no
node directory; it learns `(bus_shard, node_id)` from the join response and the first keyframe and
repoints on receipt; on losing its bus shard (2 s timeout) it closes the affected sockets so the
node sees a session drop and enters the phase-2 pause path. `hash(game_id) mod 8`.

**Import-boundary test.** `tests/test_layering.py` walks each service's imports and asserts
`edge`, `api_gateway`, `matchmaker`, `allocator` never reach `game_engine`/`real_time`/`rules`,
and that `shared/` never imports `game_engine`/`real_time`/`server`. I1 and I2 become mechanically
enforced instead of documented.

**Storage migration.** sqlite → Postgres (`users`, `game_results` in daily partitions). Redis
keys `sess:`, `game:`, `room:`, `node:`, `log:`. `PersistenceWorker`'s thread-pool shape stays
only in the auth service where scrypt genuinely needs it; the async services use asyncpg directly.

**Client, phase 4.** This is where `client/shell.py` actually changes shape: register/login/rooms/
queue move from WS messages to REST calls against the API gateway, the client holds a JWT and
opens its WS to the edge with it, and refresh-token rotation gets a code path. `view/` and
`input/` remain untouched throughout.

**Dev harness.** `compose/docker-compose.yml` brings up NATS, Redis, Postgres and all seven
services. Retire `server/main.py` at the end of the phase.

---

## Phase 5 — Spectator relay tier and lazy subjects

Today observers are recipients of the game session itself (`GameSession.observers`,
`_recipients()`), so every added viewer is work the game node does. At target scale that is 21.5M
of the 30M deliveries/s sitting on the tier that can least afford them. The relay moves all of it
off.

**Lazy subjects first, because it is the cheaper half and it is what keeps the bus viable.** The
game node currently would publish to a per-game subject unconditionally; instead
`spec.{shard}.{game_id}` and `kf.{shard}.{game_id}` are created only once a game is actually
watched. The allocator tracks watch-interest on the `game:{id}` record and the node learns of the
first watcher over `ctl.node.{node_id}`. This exploits the spec's third load-bearing fact — the
median room has zero viewers — and keeps the NATS interest table in the thousands rather than the
millions.

**`services/relay/`**, two levels:
- **L1** subscribes to `spec.{shard}.{game_id}` for watched games and caches, per game, the latest
  keyframe (10 s internal cadence, watched games only) plus a small delta ring buffer (~6 KB).
- **L2** holds viewer sockets and pulls from L1. A mid-game joiner is served keyframe + buffered
  deltas unicast from the L1 cache and *then* joined to the live stream — **the game node is never
  asked anything**, which is the whole point of the tier.

**Relays never parse payloads.** They route on the envelope only, exactly as the edge does — which
is what makes I1 structurally true rather than merely intended. The phase-1 envelope-level `seq`
is what allows this; a relay that had to open a payload to find a sequence number would break the
invariant.

The ≤1 s delivery delay is deliberate and doubles as anti-stream-sniping, so no work is needed to
achieve it beyond not fighting it. Keep a short post-game cache so a rejoin after `ended` (phase
0's room FSM) resolves to the relay rather than to a dead room.

**Game-side changes.** `GameSession.observers` and `add_observer`/`remove_observer` go away, along
with the `GameRegistry._player_to_game` observer mapping — the CLAUDE.md gotcha about observers
being tracked in two places stops existing, because observers stop being a game-node concept
entirely. `_recipients()` becomes the two players plus, if watched, one publish to the spec
subject. Join flow moves to the API gateway returning a relay hint.

**Python note.** Fewer sockets per L2 instance than the spec's 60k; scale out in instance count.
L1's per-game cache is the memory-sensitive part, so size L1 by watched games and L2 by viewers.

---

## Phase 6 — Data tier: sharding, identity, retention

Phase 4 put Postgres behind the result writer and auth. This phase makes it survive the write rate
and the row count.

**Global identity table.** Per-region user sharding cannot answer "who is `etty`, and where do
they live" from a cold login in another region. One globally replicated `identity` table —
`email → (user_id, home_region)`, ~5 GB at target — read on every login and essentially never
written. Everything else about a user (rating, history, credentials) stays in the home region's
shard. `services/auth/` and `services/api_gateway/` are the only readers.

**`game_results` partitioning.** Daily partitions, retention 30 days, dropped with `DROP
PARTITION` rather than `DELETE` — the difference between a metadata operation and rewriting
billions of rows. Add a partition-maintenance job (create tomorrow's, drop day-31). Permanent
per-user aggregates and last-20-games live outside the partitioned table so history survives
retention.

**Shard key.** Shard on `user_id`, explicitly **not** on rating: rating is mutable and every Elo
update would migrate the row. Cross-shard reads are confined to the result writer, which already
batches, and which writes both players' results in one transaction with the `game_results` primary
key as the idempotency key.

**What must remain true:** Postgres can be entirely down and live games keep playing. Nothing on
the frame path touches it. This phase must not introduce a synchronous PG read into the game node
or the edge — the import-boundary test from phase 4 gets a companion assertion that neither
imports the DB client.

---

## Phase 7 — Regions

A region is a full self-contained stack: its own bus shards, Redis fleet, game nodes, edges,
relays, matchmaker, allocator, and PG shard. Nothing on the frame path crosses a region boundary,
which is the only way the 120/180 ms SLO is reachable.

- **Region selection** at login, from the identity table's `home_region`, with latency-based
  override for play (you can play where you are, your data lives where you registered).
- **No cross-region quick match**, per spec §6. What degrades in a small region is matchmaking
  liquidity, not capacity — the phase-0 band widening is the mitigation, and the cap of ±400 is
  what bounds how bad the pairing gets before the queue gives up.
- **Regional config** lives in one place: `config/regions.py` naming bus clusters, Redis
  endpoints and PG shards per region, so no service hardcodes an endpoint.
- Explicit rooms are the one cross-region-adjacent case: a room code is regional, and joining
  a code from another region either routes you to that region (accepting the latency, since you
  chose it) or refuses. Pick one and encode it in the room record.

---

## Phase 8 — Deployment and observability

**Kubernetes.** One Deployment per stateless tier autoscaling on its own signal (HTTP RPS for the
gateway, KDF queue depth for auth, concurrent sockets for edge and relay, queue depth for
matchmaker and result writer, placements/sec for the allocator).

**The game tier scales down by draining, never by eviction** — there is no live migration anywhere
in this system, and games being ≤90 s is what makes that sufficient. A **150 s `preStop` hook**:
refuse new games (allocator sees the node stop renewing its capacity advertisement, keeps the 3 s
lease alive meanwhile), let existing games end naturally, exit. Edges cannot be waited out the
same way, so they drain by sending a reconnect hint and letting clients re-establish through the
phase-2 pause/resume path.

**Node failure → rebuild** (spec §11) lands here because it needs both the Redis game log from
phase 4 and the lease supervision from phase 4's allocator: lease expiry within 3 s, survivor node
assigned, `log:{game_id}` replayed, offset shifted (the outage is treated as a pause, not elapsed
game time), first keyframe repoints the edge cache. Target stall ~4–6 s. Phase 2's determinism
rules — integer ms, server-assigned timestamps in the log, `(game_time, monotonic_seq)` ordering,
no wall-clock reads or randomness in dispatch — are what make the replay faithful; this phase is
where they get tested rather than merely asserted.

**Prometheus**, promoting phase 0's registry to a real exposition endpoint per service. The
cardinality discipline built in at phase 0 is the point: never label by `game_id`, `user_id` or
`session_id`, or monitoring falls over before the system does. Export bus-shard queue depth and
`drain_loop_lag_seconds` (alert p99 > 20 ms, page p99 > 100 ms).

**Canary games** — synthetic clients playing continuously through the real stack, including
reconnect and spectator paths. These are the primary SLI because they measure the actual product
promise rather than a proxy. Whole-game tracing at 1:100,000 sampling; a 60 s game is a fully
bounded trace.

**SLOs:** own-render p99 < 120 ms, opponent-render p99 < 180 ms, spectator delay p99 < 1 s,
match-found p50 < 1 s / p99 < 10 s, > 99.9% of games complete without an infra-caused end, > 99%
reconnect success. Track login availability *separately* from game availability — phase 6's
invariant is that Postgres down means logins fail while games continue, and one alert covering
both would hide that.

**AZ spread:** within a region, bus, Redis and game tier across ≥3 availability zones, each shard
independently survivable.

---

## Verification

Each phase must leave the suite green (546 passing today) and the system end-to-end playable.

- **Every phase:** `.venv\Scripts\python.exe -m pytest`.
- **Phase 0:** `python bench/frames_per_game.py` prints frames/s/game, bytes/frame, bytes/game.
  New tests for band widening over a faked clock and for room-code length + claim idempotency.
- **Phase 1:** two clients against the monolith — verify a move produces one delta frame, not a
  full state; confirm bytes/frame against the phase-0 baseline; force a gap by dropping a frame in
  a test double and assert RESYNC → keyframe recovers the board. Sounds must still fire in the GUI
  (the op→event decoder feeding the local bus is what preserves this).
- **Phase 2:** `tests/test_scheduler_equivalence.py` over randomized scripts; the existing
  arbiter/collision suites (`test_real_time_arbiter.py`, `test_collisions*.py`) pass *unmodified*.
  Manually: pull the network on one client, reconnect within 10 s and confirm resume-by-keyframe;
  exceed the budget and confirm forfeit.
- **Phase 3:** `tests/test_schema_drift.py`; a version-mismatch handshake is rejected cleanly.
- **Phase 4:** the full suite runs against the in-process bus adapter; then
  `docker compose up` and play a real game through gateway → edge → NATS → game node → edge,
  including an observer join and a node kill (confirm the lease expires within 3 s).
- **Phase 5:** watch a live game from a third client and confirm the game node's delivery count is
  unchanged by adding viewers (that is the whole thesis of the tier); join mid-game and confirm the
  board is correct from the first frame with no request reaching the node; confirm no `spec.*`
  subject exists for an unwatched game.
- **Phase 6:** kill Postgres entirely and confirm a live game plays to completion and reports its
  result once PG returns; log in from a second region against the identity table; run the
  partition job across a simulated day boundary.
- **Phase 7:** two regional stacks in compose; confirm no frame-path traffic crosses them, and that
  a thin-region queue widens its band and eventually times out rather than matching cross-region.
- **Phase 8:** `preStop` on a node with live games drains rather than drops them; kill -9 a node
  and measure the rebuild stall against the 4–6 s target; confirm no metric series carries a
  per-game label; canary game SLIs report end to end.

## Running this as one session per phase

This document is the roadmap, not the working plan for any single phase. Each phase gets its own
session, which starts by planning that phase in detail against the code as it actually stands.

**First action on approval:** copy this file into the repo as `MIGRATION.md` and commit it, so
every later session can read it as context instead of being re-briefed. Update the phase's status
line there when a phase lands.

**How to open a phase session:** point it at `MIGRATION.md` and the phase number, e.g.
*"Plan phase 2 of MIGRATION.md — the discrete-event scheduler."* Each session should re-verify the
entry criteria below before planning, because earlier phases will have moved the code.

| Phase | Status | Entry criteria | Done when |
|---|---|---|---|
| 0 | not started | none | bench prints real frames/s/game and bytes/frame; band widening, 16-char codes and the room FSM are in with tests |
| 1 | not started | phase 0's byte baseline recorded | a move produces one delta frame; seq gap → RESYNC → keyframe recovers; `EVENT` channel deleted; client renders and plays sound from deltas |
| 2 | not started | phase 1 done (keyframes exist for resume) | equivalence harness green over randomized scripts; existing arbiter/collision tests pass *unmodified*; `GameShard` replaces per-game tick tasks; 10 s pause budget works end to end |
| 3 | not started | phase 1 done (protocol has stopped moving) | schema is the source of truth; drift test green; handshake negotiates a major version |
| 4 | not started | phases 1–3 done | seven services under compose; full suite green on the in-process bus adapter; import-boundary test green; `server/main.py` retired |
| 5 | not started | phase 4 done | viewer count no longer affects game-node delivery count; no `spec.*` subject for an unwatched game; observers gone from `GameSession` |
| 6 | not started | phase 4 done | PG fully down and games still play; identity table serves a cross-region login; partitions rotate |
| 7 | not started | phases 5 and 6 done | two regional stacks with no frame-path traffic between them |
| 8 | not started | phase 7 done | drain, rebuild-within-6 s, and canary SLIs all demonstrated |

Phases 5 and 6 are independent of each other and can be taken in either order. Everything else is
sequential.

## Explicitly not in this plan

**Go engine rewrite** — the game tier stays Python; the density cost is covered in Context above.
**TypeScript client** — the OpenCV Python client is carried forward through every phase.
**Binary wire format** and **move history / replays** — both are ruled out by the spec itself
(§3 makes JSON a hard constraint, Appendix C lists both as out of scope), and deltas at ~105–150 B
already come in under the egress budget without them. **Bot resistance** — the spec's position is
that a competent bot wins and won't be caught; the 10 cmd/s ceiling from phase 4 is the only
mitigation in scope. **Live migration of games** — structurally excluded everywhere, and phase 8's
drain strategy depends on its absence.

The phase-3 schema stays language-neutral even though nothing else consumes it today. That is not
wasted work: it is what makes the drift test possible, and it leaves the door open if the Go engine
or a browser client ever comes back.
