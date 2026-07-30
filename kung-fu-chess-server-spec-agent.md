# Kung-Fu Chess — Server Implementation Spec

Scope: what must be built. Rationale, capacity derivations, tradeoff analysis, and measurement plans are omitted.

Target scale: ~1.43M concurrent games / 10M concurrent users at peak. Games last 30–90 s.

---

## 1. Non-negotiable rules

| # | Rule |
|---|---|
| I1 | The game node is the sole authority. No client, gateway, relay, or bus node evaluates a rule. Relays treat frames as opaque bytes; gateways parse only the envelope, never the payload. |
| I2 | One-directional layering: `model ← rules/events ← real_time ← game_engine`. The shared wire contract depends only on `model` and is a language-neutral schema compiled into both the Go engine and the TS client. Nothing else imports it. |
| I3 | The arbiter is the only publisher of move/capture/end events. Everything else subscribes. |
| I4 | Temporal model is closed-form: `time_at_cell = start + (index + 1) × DELAY`. Do not replace with ticks. This enables the discrete-event scheduler, pause-by-offset, and sparse frames. |
| I5 | The wire carries absolute times against a server clock, never sampled progress. |
| I6 | Change coalescing: one visible change ⇒ at most one frame per game per drain pass. |
| I7 | Tests are deterministic: clock interface, explicit `advance_time(ms)`, no sleeps. Multi-node tests use a shared virtual clock. |

Additional hard constraints:
- **JSON on the wire.** Deltas ~150 B; full state ~1.5 KB. Deltas are mandatory.
- **No client-side engine.** Client interpolates from absolute times and renders local non-authoritative input affordances. No prediction, no rollback, no reconciliation.
- **Latency SLO.** p99 keypress → commanding player's own screen < 120 ms; p99 → opponent's screen < 180 ms.

Timebase: all engine timestamps are integer milliseconds in *game time*. `wall_time = game_time + pause_offset_ms`.

---

## 2. Tiers

| Tier | Stateful? | Language | Scaling signal | Responsibility |
|---|---|---|---|---|
| API Gateway | no | Python/FastAPI | HTTP RPS | register, login, refresh, profile, history, room create/join, quick-match enqueue |
| Auth Service | no | Python | KDF queue depth | password hashing, token issuance; separate deployment so KDF never competes with simulation CPU |
| WS Player Gateway ("edge") | socket-affine only | Go | concurrent sockets | TLS, JWT verify, rate limit, publish commands to bus, demux frames to sockets |
| Spectator Relay | no (cache only) | Go | concurrent sockets | read-only fan-out, ≤1 s delay |
| Matchmaker | in-memory queues | Python | queue depth per shard | sharded by (region, rating bucket), no global consistency |
| Game Allocator | no (Redis-backed) | Python | placements/sec | placement, directory, node supervision, room lobbies |
| Game Node | **yes — authoritative** | Go | concurrent games | the only tier that knows the rules; ~20,000 games per node |
| Result Writer | no | Python | queue depth | consumes terminal events, writes `game_results`, applies Elo in batches |
| NATS | no | — | msgs/sec per cluster | sharded into independent clusters |
| Redis | ephemeral | — | keys / ops | game logs, session directory, rate limiters, room registry |
| PostgreSQL | durable | — | write rate | users and game results only; off the hot path |

Scaling rules:
- Every stateless tier autoscales on its own signal.
- **The game tier scales down by draining, never by eviction.** A node refuses new games and empties itself in ~2 minutes. There is no live migration anywhere in this system.
- Fleet at peak: ~650 machines; game tier ~90 nodes (16 vCPU, 32 GB RAM), 20,000 games each.

---

## 3. Bus topology (NATS)

`bus_shard = hash(game_id) mod K`, K = 8 per region. Shards are independent clusters.

**Both hot-path directions cross the bus.**

- **Inbound:** `cmd.{shard}.{node_id}` — one subject per game node, subscribed by that node alone, published to by any edge holding a player socket for a game on that node. Do **not** use a per-game inbound subject.
- **Outbound to players:** direct edge addressing, `edge.{edge_id}`.
- **Outbound to spectators:** `spec.{shard}.{game_id}`, created lazily for watched games only.

Delivery is at-most-once (core NATS) in both directions:
- **Outbound loss:** sequence gaps trigger a keyframe request.
- **Inbound loss:** no acks, no retry, no dedupe. A dropped command is a move that never happened; the player re-presses.

---

## 4. Edge (WS Player Gateway)

- Holds player sockets only. Never dials a game node. Its entire outbound connection set is to its bus shards — no node directory, no node health state, no re-dial logic.
- Token-bucket rate limit **10 cmd/socket/s, burst 20**, applied *before* the publish.
- Parses the envelope only. Envelope carries `(game_id, session_id, seq, client_ts)`.
- Learns `(bus_shard, node_id)` for a game from the join response and the first keyframe; caches it against the socket.
- **Cache invalidation:** a rebuilt game lands on a new node; the rebuilding node's first keyframe carries the current `node_id` and the edge repoints on receipt. Commands published to the dead node's subject in the interim are dropped for want of a subscriber.
- **Bus loss:** if an edge loses its bus shard (connection timeout **2 s**), it closes the affected player sockets. The node then sees the session drop and enters pause-by-offset. The 2 s timeout must stay well under the 10 s pause budget.
- Session routing: Redis `sess:{user_id}` updated on heartbeat; new logins evict old sockets via `session.evict` ("last login wins").

---

## 5. Game node (engine)

**Process model.** Go process with S shards, one goroutine/OS thread per shard. Games assigned by `hash(game_id) mod S`. No locks on game state.

**Scheduler.** Discrete-event, not tick-based: a per-game event heap plus a per-shard outer heap. ~4 events per move.

**Command handling.** The node subscribes to exactly one subject, `cmd.{shard}.{node_id}`, and accepts no inbound connections. On arrival: route to owning shard goroutine by `hash(game_id) mod S`, stamp the authoritative arrival timestamp there, validate against authoritative state, schedule events. Rejections are unicast to the originating edge.

**Frame emission.** Serialize JSON once per frame, write N times. Cap: **1 frame per game per 10 ms**. At most one frame per game per drain pass (I6).

**Pause as time offset.** On pause, record `paused_at`. On resume, add elapsed to `pause_offset_ms`, re-key the outer heap entry, and emit a keyframe.

**Determinism.** Integer ms timestamps; server-assigned timestamps in the command log; ordering by `(game_time, monotonic_seq)`.

---

## 6. Control plane

**Matchmaker.** In-memory queues sharded by (region, rating bucket). Rating band ±100, widening +50 every 5 s, capped at ±400. No cross-region quick match.

**Game log.** Asynchronous batched writes to Redis, `log:{game_id}`, TTL = game lifetime. Used solely for rebuild after node failure. Not durable, not a replay feature.

**Game Allocator** (stateless, Redis-backed). Four jobs:
1. **Placement** — select least-loaded game node, write `game:{id}`, issue `create_game` on `ctl.node.{node_id}`.
2. **Directory** — resolve `game:{id}` and room codes (16-char Crockford base32, ~80 bits).
3. **Supervision** — node liveness via Redis lease, **3 s TTL renewed at 1 s**; on expiry, order a game rebuild.
4. **Room lobbies** — owns `room:{code}` with the same claim-then-place pattern as `game:{id}`.

---

## 7. Rooms (create / join / roles)

**A room is a lobby that has not yet earned a game.** No game node, no `game_id`, no scheduler exists until a second player claims the open seat. At that instant the flow becomes identical to quick match.

Endpoints:
- `POST /v1/rooms` → creates lobby, returns room code, `role=host`.
- `POST /v1/rooms/{code}/join` → single endpoint; the **response tells the client its role**. The client never decides or infers its role.

**The claim.** Seat 2 is won by one atomic Redis operation (`HSETNX` on the room record):
- **Success** → caller is player 2. Allocator immediately picks a node, writes `game:{id}`, sends `create_game`, flips `room:{code}.state` → `live`, sets `game_id`.
- **Failure** → caller is a spectator for this room, permanently. Return the room record: `game_id` + relay hint if `live`, or `state=waiting` if the transition hasn't landed (client retries once).

**Idempotency.** Check `seat2_uid == caller_uid` before treating a repeat `/join` as a new claim. The host's join on their own code and player 2's refresh must not re-issue a seat.

**State machine.** Transitions are one-way: `waiting → live → ended`. `live` never reverts. Rejoining after `ended` returns a spectator hint to the relay's post-game cache, or "room closed" after TTL.

**Room record TTL.** 10 min while `waiting`; refreshed to game lifetime while `live` (the owning game node takes over the heartbeat); 60 s grace once `ended`.

**Spectators arriving during `waiting`.** No `game_id` exists yet. Pick one at implementation time: (a) client polls `/join` until the seat is claimed, or (b) allocator parks waiting-spectator session ids on the room record and pushes a `relay_hint` when state flips to `live`. Either way, no `spec.*` subject is created before the game is live.

**Invariant — no mid-game promotion.** A spectator is never promoted to a player, under any circumstance, including a player disconnect. A dropped player pauses, then forfeits when the pause budget expires. Reusing the room means a **new game**, not a continuation.

---

## 8. Auth

Separate deployment. scrypt N=2^13, r=8, p=1. Ed25519 JWTs: access TTL 15 min (not enforced mid-game), refresh TTL 30 d, rotated with reuse detection. Gateways verify JWTs locally against cached JWKS.

---

## 9. Spectator relay

Two-level tree (L1 → L2). Subscribes to `spec.{shard}.{game_id}`; caches keyframes from `kf.{shard}.{game_id}` at a **10 s** internal cadence for watched games only. Serves viewers with ≤1 s delay. Read-only — no spectator input reaches the game tier. Keeps a short post-game cache.

---

## 10. Wire protocol

- Language-neutral JSON schema, compiled into both the Go engine and the TS client.
- Positional-array delta encoding; a typical move frame is ~105–150 B.
- Absolute times against the server clock (I5). Never send sampled progress.
- Sparse: zero frames during idle periods.
- Keyframes are the universal recovery path — reconnect, rebuild, backpressure, and gap detection all resolve via keyframe delivery.
- Socket liveness via WebSocket ping/pong.
- Versioning: major version negotiated at handshake; minor changes additive only.

---

## 11. Flows

**Register / login.** Regionally sharded, with a global identity table.

**Quick match.** In-memory queue matching with widening rating bands; on match, allocator places a node and issues `create_game`.

**Move round trip** — path is symmetric, `edge → bus → node → bus → edge`, and nothing on it holds a cross-tier connection:
1. Client → edge: keypress serialized to a WS frame.
2. Edge: token bucket; envelope parse only; look up cached `(shard, node_id)` — no directory call on the hot path.
3. Edge → bus: publish to `cmd.{shard}.{node_id}`, `shard = hash(game_id) mod 8`.
4. Bus → node: single subscriber on that subject.
5. Node: stamp arrival time, route to shard goroutine, validate, schedule events.
6. Node → bus: 1–3 delta frames, each serialized once, published to `edge.{edge_id}` per distinct edge, and to `spec.{shard}.{game_id}` if watched.
7. Bus → edges → clients: edges demux frames onto sockets.

**Game end → Elo.** Terminal event → Result Writer → single Postgres transaction; the `game_results` primary key is the idempotency key. K-factor 32, flat, no provisional period. Default rating 1200.

**Disconnect → pause → reconnect.** Node enters pause-by-offset on session loss. Budget: **10,000 ms total per player per game** (not per pause). Exhausted budget ends the game by forfeit. Keyframe on resume.

**Node failure → rebuild.** Allocator detects lease expiry (3 s), assigns a survivor node, which replays `log:{game_id}` from Redis. Total stall ~4–6 s. The rebuilding node's first keyframe repoints edge caches.

---

## 12. Deployment & observability

- Kubernetes; game nodes carry a **150 s preStop drain hook** (refuse new games, empty, exit).
- Docker Compose harness for development.
- Prometheus metrics with **no high-cardinality labels** (never per-game). Export bus shard queue depth. Track canary-game SLIs.
- Within a region, spread the bus, Redis fleet, and game tier across ≥3 availability zones; each shard independently survivable.
- Retention: 30 days of `game_results` in daily partitions, dropped by `DROP PARTITION`.

---

## 13. Build order

0. Instrument the prototype.
1. Delta protocol.
2. Discrete-event scheduler (replace the 50 ms tick).
3. Schema generation for the shared wire contract.
4. Tier separation.
5. Go engine rewrite.
6. Spectator relays.
7. Database sharding.

---

## Appendix A — Constants

| Constant | Value |
|---|---|
| DEFAULT_MOVE_DELAY_MS | 1000 (per square) |
| Long rest | 2 × move delay |
| Short rest (jumps) | 1 × move delay |
| MATCH_ELO_RANGE | ±100, widens +50 per 5 s, cap ±400 |
| K_FACTOR | 32 |
| DEFAULT_RATING | 1200 |
| Reconnect / pause window | 10,000 ms total per player per game |
| Room lobby TTL (waiting) | 10 min |
| Room record TTL (ended) | 60 s |
| Command rate limit | 10/s, burst 20, per socket |
| Frame emission cap | 1 per game per 10 ms |
| Relay keyframe cadence | 10 s (internal, watched games only) |
| Access token TTL | 15 min |
| Refresh token TTL | 30 d |
| KDF | scrypt N=2^13, r=8, p=1 |
| Room code | 16 chars Crockford base32 |
| Node lease TTL | 3 s, renewed at 1 s |
| Game-node density | 20,000 games |
| Bus shards | 8 per region, `hash(game_id) mod 8` |
| Edge bus-connection timeout | 2 s |
| Game-result retention | 30 days, daily partitions |

## Appendix B — Namespaces

**NATS subjects:** `cmd.{shard}.{node_id}`, `ctl.game.{shard}.{node_id}`, `edge.{edge_id}`, `spec.{shard}.{game_id}`, `kf.{shard}.{game_id}`, `ctl.alloc`, `ctl.node.{node_id}`, `evt.result`

**Redis keys:** `sess:{user_id}`, `game:{id}`, `room:{code}`, `node:{id}`, `log:{game_id}`

## Appendix C — Explicitly out of scope

Binary wire format · move history and replays · durable game log · cross-region quick match · spectator interactivity · client-side prediction · one-session-per-user enforcement · per-game process isolation · strong rating consistency · bot resistance · live migration of games · global matchmaking consistency · direct edge→node dialing
