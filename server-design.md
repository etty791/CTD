# Kung-Fu Chess — Server Design (Condensed)

**Scale target:** 10M concurrent users, ~1.43M concurrent games. Optimizes for defensible reasoning over operational realism. Every number is an *estimate from an unmeasured baseline* (see §Measurements).

---

## 1. Invariants (must survive the rewrite)

- **I1** Engine is sole rule authority — gateways/relays/bus only move opaque bytes.
- **I2** Strict layering: `model` ← `rules/events` ← `real_time` ← `game_engine`; `shared` wire contract depends only on `model`.
- **I3** Only the arbiter publishes move/capture/end events; everything else subscribes.
- **I4** Closed-form time model: `time_at_cell = start + (index+1) × DELAY`. **The single most valuable property in the codebase** — enables the discrete-event scheduler, pause-as-offset, and sparse wire frames.
- **I5** Wire carries absolute times vs. server clock, never sampled progress.
- **I6** Change coalescing: any number of internal events in one drain pass ⇒ one frame.
- **I7** Deterministic tests: fake clock, `advance_time(ms)`, no sleeps.

---

## 2. Load Model

7 people/room (2 players + 5 viewers), 60s games, ~1 move/s/game, ~3 frames/s/game:

| Quantity | Value |
|---|---|
| Concurrent games | 1.43M |
| Players / viewers | 2.86M / 7.14M |
| Games created=ended | 23.8k/s |
| Matchmaking requests | 47.6k/s |
| Frames encoded | 4.3M/s |
| Deliveries (players/viewers) | 8.6M/s / 21.5M/s |
| Egress: full state vs delta | 360 Gbps (not viable) vs **36 Gbps** (viable) |
| Scheduler events | ~5.7M/s |
| Redis log writes | ~120 MB/s |

**Most fragile number:** 3 frames/s/game (derived, not measured) — everything downstream scales linearly with it (Measurement #1).

**10M = peak**, not sum; daily avg 2–3M. Game tier scales down by **draining** (refuse new games ~2 min, empty out), never eviction — only possible because games are short.

**Regional split:** capacity scales cleanly per region; what degrades is **matchmaking liquidity** in small regions (thin rating-bucket tails) — mitigated by band-widening, not by more compute. Cross-region quick match stays forbidden (latency SLO).

---

## 3. Constraints

- **JSON wire (hard):** delta ~150B vs full state ~1.5KB. Cost: ~29 Gbps extra egress + ~6 cores — expensive because of egress pricing, cheap on CPU only because frames are encoded once per game, not per recipient. Compression off for deltas (kills serialize-once), on for keyframes.
- **No client-side engine (hard):** client only interpolates; local "affordance" UI (selection/ghost path) never touches state.
- **Latency SLO (hard):** p99 own-render <120ms, opponent <180ms, achievable only intra-region. Budget ~40–65ms typical.
- **`DEFAULT_MOVE_DELAY_MS` (1000ms) must not shrink** — shortening it makes latency *more* perceptible (RTT becomes a bigger % of travel time) and roughly doubles fleet load.
- **Language:** Go for game tier & edge/relay (goroutine-per-shard, GC pauses irrelevant vs 1000ms delay). Python/FastAPI fine for anything off the frame path (API, auth, matchmaker, allocator, result writer).

---

## 4. Architecture

Tiers: API Gateway, Auth, WS Player Gateway, Spectator Relay (L1/L2), Matchmaker, Game Allocator, Game Node (only stateful/authoritative tier), Result Writer, NATS (sharded bus), Redis (ephemeral), PostgreSQL (durable, users + results only, off hot path).

**Three structural moves:**
1. Discrete-event scheduler replaces 50ms tick (28M ticks/s → 5.7M real events/s).
2. Two-tier spectator relay removes 21.5M/30M deliveries/s from game tier.
3. **Direct edge addressing** for players + lazy per-game subjects only for watched games — keeps bus interest table in thousands, not millions (exploits the assumption that median room has 0 viewers).

---

## 5. Edge Tier

**API Gateway:** stateless REST (register/login/refresh/profile/rooms/queue/watch). `/v1/queue` returns a ticket immediately; match result comes over WS, not HTTP (can't hold 47.6k/s of open connections).

**WS Player Gateway:** holds sockets only, ~40KB/socket.
- Inbound: rate limit 10 cmd/s/socket (burst 20), envelope parsed but **payload never inspected** (I1), forwarded to `ctl.game.{shard}.{node}`.
- Outbound: one subscription per gateway (`edge.{edge_id}`), demuxed by `session_id`.
- Backpressure: 256KB buffer cap; on overflow, drop all pending deltas (not just one) and request a keyframe — safe because deltas are only meaningful in sequence.
- JWT verified at connect only, cached JWKS, no round trip; **not re-checked mid-game** even if token expires.

**Session routing:** "last login wins" — new login evicts old socket via `session.evict`; the evicted game isn't forfeited, it just enters the normal pause/reconnect path (device-switching becomes free).

---

## 6. Bus (NATS)

Chosen over Redis Pub/Sub (which broadcasts to every node regardless of interest) for wildcard subjects, queue groups, and leaf-node topology matching the relay fan-out tree.

- Sharded into **K≈8 independent clusters/region** via `hash(game_id) mod K`; no cross-shard traffic on the game path.
- **Addressing table:**
  - Client→engine: `ctl.game.{shard}.{node_id}` (~90 subjects)
  - Engine→player: `edge.{edge_id}` (~140 subjects, direct addressing)
  - Engine→spectators: `spec.{shard}.{game_id}` — **lazy, only if watched**
  - Keyframe cache: `kf.{shard}.{game_id}` — lazy
- Core NATS at-most-once (no JetStream) on the frame path — lost frame = lost delta, self-heals via sequence-gap → keyframe request. JetStream used *only* for `evt.result` (rating correctness matters).

---

## 7. Game Tier (Engine)

One Go process/node, **S shards** (1 goroutine/OS thread each), `hash(game_id) mod S`, games never move, **no locks anywhere**.

**Discrete-event scheduler:** two-level heap (per-game heap of ~4-12 pending events; per-shard outer heap keyed by wall time). ~4 events/move (2.5 CELL_ENTER + MOVE_DONE + REST_END) → 5.7M events/s fleet-wide, comfortably under 1 core/node. **Simulation is never the bottleneck.**

**Command handling:** validate ownership/idle/geometry → schedule events → async log append → mark dirty. Rejections are unicast only, carry `client_seq` for UI un-dimming. **Timestamps never backdated** (would require re-simulating the past + is exploitable).

**Frame coalescing:** I6 holds structurally; additionally rate-limited to 1 frame/game/10ms as a safety cap (never fires in normal play).

**Pause = integer offset** (`pause_offset_ms`); resume just re-keys one heap entry + sends a keyframe. Same mechanism used for reconnect, resume, rebuild, backpressure recovery, and relay join.

**Replay determinism (key resolution of a tension the brief doesn't name):** brief says "no bit-exact determinism" but also requires rebuild-by-replay — contradictory unless replay is deterministic. Resolved by: integer ms only, log records *assigned* server timestamp, `(game_time, monotonic_seq)` ordering, no randomness/map-iteration/wall-clock reads in dispatch. Reinterpreted as "no cross-engine agreement required, only self-replay fidelity."

---

## 8. Control Plane

**Matchmaker:** sharded by (region, 100-point rating bucket), **in-memory queues** (loss is cheap — same "keep waiting?" UX as normal). Band ±100, widens 50/5s, cap ±400. Hot buckets replicated into N sub-queues (safe since matching isn't order-sensitive). Elo K=32, default 1200, no provisional period.

**Game log (Redis, ephemeral):** exists only to rebuild elsewhere; TTL=game lifetime. Async, batched every 10ms — nothing on command path waits for Redis. ~120 MB/s, ~10GB live. Rejected alternative: buddy-node replication (faster failover, 2× memory + split-brain risk) — named as the upgrade path if rebuild time (Measurement #3) proves unacceptable.

**Allocator:** stateless, does placement (power-of-two-choices), directory maintenance (game_id → node), and supervision (3s lease, redistribute on expiry). Room codes: 16-char Crockford base32 (~80 bits, up from 6 chars/~30 bits — collision/brute-force fix). Off the frame path.

---

## 9. Auth Tier

Isolated pool so KDF never steals simulation CPU. Real verification rate ~1-2k/s (refresh tokens mean most reconnects skip the KDF). **Chosen: scrypt N=2^13** (~25ms) vs brief's default N=2^14 — halves offline-attack cost, justified only combined with rate limiting (5/15min per account, 20/min per IP, 200/min per /24, circuit breaker at 2s queue depth). Prefer argon2id if available. EdDSA tokens, access 15min / refresh 30d (rotated, reuse-detected).

---

## 10. Spectator Relay

Two-level fan-out (L1 caches, L2 holds ≤60k sockets each); relays **never parse payloads** (I1 made structurally true, not just intended).

**Joining mid-game:** L1 caches latest keyframe (10s cadence, watched-only) + delta ring buffer (~6KB/game); joiner gets keyframe+deltas unicast then joins live stream — no ask to the game node.

**1s delay is also anti-stream-sniping** — deliberate feature, not just tolerance.

**What breaks (in priority order):** join storms (10k viewers/sec = 10k TLS handshakes, mitigated by spreading admission + handshake-rate refusal), discovery features (out of scope, would create correlated storms), single game >1M viewers (needs 3rd relay tier or CDN — explicitly out of scope).

---

## 11. Wire Protocol

`shared/` becomes a language-neutral schema generating both Go encoder and TS decoder — preserves I2 across the language split. Additive-only within a major version; unknown fields/opcodes ignored, not errors.

- **Keyframe:** full state (pieces, positions, absolute times, scores, phase) — sent on join/reconnect/resume/backpressure-recovery/gap-detection.
- **Delta:** positional-array ops (`m` move, `x` capture, `r` rest, `sc` score, `ph` phase, `end`) — measured ~105B/move, ~140B/capture, ~1.4KB keyframe (beats the 150B budget).
- **Command:** `{t:"c", g, q(seq), p(iece), to}`. **Heartbeat deleted** — idle games send zero frames (client extrapolates from t0/t1 against a smoothed clock offset). Liveness is WS ping/pong only (30s, transport-level).
- **Resync**, one mechanism, three triggers: sequence gap, reconnect, backpressure recovery.

---

## 12. Data Flows (summary)

- **Register/Login:** one global replicated identity table (email→user_id+home_region, ~5GB) lets login work from any region despite per-region PG sharding. scrypt is the only KDF call in the system.
- **Quick match:** ticket via HTTP → in-memory matchmaker pairs → allocator picks least-loaded node → game seeded, keyframe sent as game_start.
- **Move round trip:** command → gateway (rate-limit, parse envelope only) → owning node validates+schedules → **one JSON encode**, published to both players + relay (if watched) → 3 frames total per move (start, land, rest-end) from one command.
- **Game end → Elo:** terminal event → JetStream (the one durable path) → Result Writer batches 500/200ms → PG insert with `ON CONFLICT DO NOTHING` as idempotency key → same-transaction Elo update → Redis rating refresh. Residual risk: node dies between terminal event and JetStream publish = one lost rating update (accepted, stated).
- **Disconnect/pause/reconnect:** pause = remove from heap + schedule 10s expiry; reconnect = offset shift + keyframe; reconnecting is nearly free (game never depended on the socket). Both-disconnect = no-contest end.
- **Node failure → rebuild:** allocator detects lease expiry (≤3s) → survivors read seed+log from Redis, replay deterministically, shift offset (treated as a pause, not real elapsed time) → keyframe. Total user-visible stall: **~4-6s** for 20k games. This recovery-time number is what sets game-node density (§13.2).

---

## 13. Capacity

**~650 machines total** at 10M peak, dominated by socket-holding tiers (gateways/relays ~290 nodes). **Only ~90 run the actual game simulation** — simulation itself is <1 core/node, the system is CPU-idle by design.

**Why only 20k games/node (not 200k, which CPU could support):**
1. Rebuild time scales linearly with density — 20k games ≈ 5s rebuild; 200k ≈ 40s (longer than a game).
2. Blast radius: 20k/72 nodes = 1.4% of live games per failure vs. 12.5% at higher density.
3. No profiling data exists — running at 5% of estimated capacity survives being wrong by 10×.

**Client egress ~28 Gbps** (under the 36 Gbps budget — positional-array encoding beats the estimate). **Internal bus egress (~10 GB/s) is larger than client egress** — usually-invisible cost that actually sizes the bus.

PG: `game_results` partitioned daily (~2B rows/day), rating is deliberately **not** the shard key (mutable, would cause row migration).

---

## 14. Failure Analysis

Key properties:
1. **PostgreSQL can be fully down and games keep playing** — nothing on the frame path touches it.
2. **Redis can lose the game log with zero visible impact** — its only consumer is a rebuild that may never happen.
3. **Every recovery path (reconnect, resume, rebuild, backpressure, gap, relay-join) terminates in the same keyframe mechanism** — the single biggest reduction in failure-mode surface area, enabled by I5 (absolute-time wire).

Deploys: rolling drain (2-min wait, no live migration — only possible because games ≤90s). Gateways drain via reconnect-hint since sockets can't be waited out.

---

## 15. Key Decisions on Open Questions

- **Client prediction:** interpolation + non-authoritative local affordances only (piece visibly "sent" but doesn't move until confirmed). Rejected: local optimistic movement (needs rollback, worse than the delay) and server backdating timestamps (requires re-simulating the past, exploitable via inflated RTT claims).
- **Repeated pauses:** **10s total pause budget per player per game** (not per-disconnect) — closes a griefing vector (yanking network cable near a loss) for the cost of two integers.
- **Retention:** 30 days detailed `game_results` (daily partitions, dropped not deleted), permanent per-user aggregates/last-20-games. 30 days is a guess; cut this first if storage is the binding cost.
- **Abuse:** bots are **honestly out of scope** — a competent bot wins, full stop. In-scope mitigations: 10 cmd/s hard ceiling, a non-move-log timing-jitter digest (bot detection signal without violating the no-replay decision), enforcement via queue segregation (not bans, since it's robust to false positives). Standard rate limiting + JWT-gated subscriptions cover DDoS posture.
- **Versioning:** major version negotiated at handshake, additive-only within a major — cheap (4 bytes) insurance since cached browser clients can outlive multiple deploys.

---

## 16. What Was Traded Away (top risks)

| Traded | Bought | Residual risk |
|---|---|---|
| Binary wire format | Debuggable JSON, no schema compiler on hot path | ~29 Gbps extra egress + 6 cores — most expensive tradeoff in $ terms |
| Move history/replay | Massive write reduction | No anti-cheat, no disputes, no replay feature ever |
| Durable game log | 120MB/s vs a WAL on 1.43M cmd/s | Small window of lost commands on node death (keyframe erases the visible discrepancy) |
| Cross-region matchmaking | Latency SLO achievable | Thin pools / more "keep waiting" prompts in small regions |
| Per-game process isolation | ~90 nodes instead of thousands | **A panic in one game's dispatch could kill 20k games** — highest-severity residual risk; mitigated by per-dispatch `recover()` (kills one game only) + fuzzing |
| Client-side prediction | No rollback code, structural server authority | ~45ms of masked (not removed) input latency |
| Bot resistance | Enormous scope reduction | A determined bot beats humans and won't be caught — stated openly |

(Full list of 12 items in the original; these are the highest-stakes.)

---

## 17. What Must Be Measured First (priority order)

1. **Frames/s/game from real play** — everything in the delivery/egress math is linear in this assumed 3/s.
2. Bytes/µs per delta encode on the real encoder.
3. **Rebuild time vs. games/node** — sets density, fleet size, blast radius.
4. Memory per live game (with real move histories, not empty boards).
5. NATS throughput with realistic subject churn (~143k lazy subjects) — most likely-wrong assumption, manifests as latency spikes not errors.
6. Continuous canary-measured end-to-end p99 command→render.
7. KDF wall time on the actual target instance (memory-bandwidth sensitive).

(1) and (3) can be measured on the existing single-process prototype with no new infrastructure, before committing to this design.

---

## 18. Migration Path (staged, each phase independently valuable)

0. Instrument the prototype (measurements 1,2,4).
1. Delta protocol + keyframes, drop heartbeat (single process).
2. Discrete-event scheduler replaces tick — existing deterministic tests must pass **unchanged**.
3. Extract language-neutral wire schema.
4. Split tiers (API/auth/gateway/matchmaker/allocator + NATS/Redis); game tier still Python.
5. Rewrite game tier in Go; **differential-test against the Python engine by replaying recorded logs through both** (a free byproduct of replay determinism, §7.6).
6. Spectator relay tier + lazy subjects.
7. PG sharding, regions, identity table, result writer.

---

## 19. Observability

- **Cardinality discipline:** never label metrics by `game_id`/`user_id`/`session_id` — would create ~2B series/day and take monitoring down first.
- `drain_loop_lag_seconds` is the single most important internal metric (scheduler keeping up); alert p99>20ms, page p99>100ms.
- Whole-game distributed tracing at 1:100,000 (a 60s game is a fully bounded trace).
- **Canary games** (synthetic clients playing continuously through the real stack) are the primary SLI — measure the actual product promise, not a proxy, and continuously exercise reconnect/spectator paths.
- Core SLOs: own-render p99<120ms, opponent-render p99<180ms, spectator delay p99<1s, match-found p50<1s/p99<10s, >99.9% games complete without infra-caused end, >99% reconnect success. Login availability tracked *separately* from game availability (PG down ≠ games down).

---

## 20. Summary — The Four Load-Bearing Facts

1. **The temporal model is closed-form (I4)** — makes the scheduler, pause, sparse wire, and replay-rebuild all possible; the whole design spends this one property.
2. **Games last 60 seconds** — eliminates live migration, makes draining a full deploy strategy, makes an ephemeral log sufficient, bounds every recovery path.
3. **The median room has zero viewers** — makes lazy per-game bus subjects affordable and turns spectating into cheap read-only fan-out.
4. **Frames are identical for every recipient** — one encode serves seven recipients, which is the only reason the JSON constraint is affordable.

**What's explicitly not solved:** bots will beat humans and won't be caught; a panic in the shared game process can take out 20k games; a mistimed node failure silently drops one rating update; every capacity number is unvalidated until measured.
