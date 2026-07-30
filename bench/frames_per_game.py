"""Headless, deterministic bench: drives N `KungFuChessGame` instances
through scripted move sequences via `wait()` and reports the numbers every
capacity estimate in MIGRATION.md is built on - frames/s/game, bytes/frame,
events/frame (the coalescing ratio), and bytes per live game.

No server, no sockets. The frame-emission rule mirrors
`server/game_session.py`'s `_on_tick`/`flush_frame` exactly (one DELTA per
pass that published anything, nothing at all on an idle pass), and byte
measurement reuses the real `DeltaBuilder` plus the same
`Envelope.model_dump_json()` path `Connection.send` uses, so the numbers
reported here are the real ones, not an approximation of them.

Usage:
    .venv\\Scripts\\python.exe bench/frames_per_game.py --games 200 --json bench/baseline.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

# Run both as `python bench/frames_per_game.py` (script dir goes on
# sys.path[0], not the repo root) and as `python -m bench.frames_per_game`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game_engine.game import KungFuChessGame
from model.board import BOARD_SIZE
from model.piece import Color, State
from model.position import Position
from observability.metrics import default_registry
from rules.rules_engine import validate_piece_move
from server.delta import DeltaBuilder
from server.game_session import STATE_CHANGING_EVENTS
from server.server_config import TICK_MS
from shared.messages import DeltaPayload
from shared.protocol import Envelope, MessageType

DEFAULT_GAMES = 200
DEFAULT_COMMAND_INTERVAL_MS = 2000  # a piece can't be re-commanded faster
# than its own cooldown anyway (real_time/real_time_config.py's
# LONG_REST_DURATION_MS), so this is the realistic ceiling for one active
# piece and a defensible default command cadence.
DEFAULT_MAX_GAME_MS = 90_000  # the spec's <=90s game
DEFAULT_SEED = 42
BENCH_GAME_ID = "bench"


class _BenchGame:
    """One headless game plus the bookkeeping GameSession would otherwise
    do: a DeltaBuilder coalescing STATE_CHANGING_EVENTS into frames, and a
    scripted command schedule per color."""

    def __init__(self, seed: int, command_interval_ms: int):
        self.game = KungFuChessGame()
        self.rng = random.Random(seed)
        self.command_interval_ms = command_interval_ms
        self.clock_ms = 0
        self.seq = 0
        self.frame_count = 0
        self.frame_bytes: list[int] = []
        self.frame_events: list[int] = []
        # Stagger the two colors so they don't always command on the same
        # tick, which would understate the coalescing ratio.
        self.next_command_ms = {
            Color.WHITE: 0,
            Color.BLACK: command_interval_ms // 2,
        }
        self.delta = DeltaBuilder(lambda: self.game.get_snapshot().get_scores())
        for event_type in STATE_CHANGING_EVENTS:
            self.game.events.subscribe(event_type, self.delta.on_event)

    def _pick_idle_piece(self, color: Color):
        board = self.game.board
        candidates = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                pos = Position(row, col)
                piece = board.get_piece_at(pos)
                if piece is not None and piece.color == color and piece.state == State.idle:
                    candidates.append((piece, pos))
        if not candidates:
            return None, None
        return self.rng.choice(candidates)

    def _legal_destinations(self, piece, origin: Position) -> list[Position]:
        board = self.game.board
        destinations = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                dest = Position(row, col)
                if dest == origin:
                    continue
                if validate_piece_move(board, piece, dest).is_valid:
                    destinations.append(dest)
        return destinations

    def maybe_command(self, color: Color) -> None:
        if not self.game.game_active or self.clock_ms < self.next_command_ms[color]:
            return
        self.next_command_ms[color] += self.command_interval_ms

        piece, origin = self._pick_idle_piece(color)
        if piece is None:
            return

        destinations = self._legal_destinations(piece, origin)
        if destinations:
            self.game.move_request(origin, self.rng.choice(destinations))
        else:
            self.game.jump_request(origin)

    def tick(self, tick_ms: int) -> None:
        self.clock_ms += tick_ms
        self.game.wait(tick_ms)
        if self.delta.has_ops():
            self._emit_frame()

    def _emit_frame(self) -> None:
        ops = self.delta.drain()
        self.seq += 1
        payload = DeltaPayload(
            ops=ops, server_time_ms=self.game.get_snapshot().get_clock_ms()
        )
        envelope = Envelope(
            type=MessageType.DELTA,
            payload=payload.model_dump(),
            game_id=BENCH_GAME_ID,
            seq=self.seq,
        )
        body = envelope.model_dump_json()
        self.frame_count += 1
        self.frame_bytes.append(len(body.encode()))
        self.frame_events.append(len(ops))


@dataclass
class BenchResult:
    games: int
    simulated_ms: int
    total_frames: int
    frames_per_second_per_game: float
    bytes_per_frame_p50: float
    bytes_per_frame_p99: float
    bytes_per_frame_mean: float
    bytes_per_second_per_game: float
    events_per_frame_mean: float
    tracemalloc_bytes_per_live_game: float
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "games": self.games,
            "simulated_ms": self.simulated_ms,
            "total_frames": self.total_frames,
            "frames_per_second_per_game": self.frames_per_second_per_game,
            "bytes_per_frame_p50": self.bytes_per_frame_p50,
            "bytes_per_frame_p99": self.bytes_per_frame_p99,
            "bytes_per_frame_mean": self.bytes_per_frame_mean,
            "bytes_per_second_per_game": self.bytes_per_second_per_game,
            "events_per_frame_mean": self.events_per_frame_mean,
            "tracemalloc_bytes_per_live_game": self.tracemalloc_bytes_per_live_game,
            "metrics": self.metrics,
        }


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return float(ordered[index])


def _metrics_summary() -> dict:
    snapshot = default_registry.snapshot()
    summary: dict = {"counters": {}, "histograms": {}}
    for counter_sample in snapshot.counters:
        summary["counters"][counter_sample.name] = {
            "|".join(key) if key else "total": value
            for key, value in counter_sample.values.items()
        }
    for histogram_sample in snapshot.histograms:
        summary["histograms"][histogram_sample.name] = {
            "|".join(key) if key else "total": {
                "count": histogram_sample.counts[key],
                "sum": histogram_sample.sums[key],
            }
            for key in histogram_sample.counts
        }
    return summary


def run_bench(
    games: int = DEFAULT_GAMES,
    command_interval_ms: int = DEFAULT_COMMAND_INTERVAL_MS,
    max_game_ms: int = DEFAULT_MAX_GAME_MS,
    tick_ms: int = TICK_MS,
    seed: int = DEFAULT_SEED,
) -> BenchResult:
    tracemalloc.start()
    benches = [_BenchGame(seed + i, command_interval_ms) for i in range(games)]

    elapsed_ms = 0
    while elapsed_ms < max_game_ms and any(b.game.game_active for b in benches):
        elapsed_ms += tick_ms
        for bench in benches:
            if not bench.game.game_active:
                continue
            bench.maybe_command(Color.WHITE)
            bench.maybe_command(Color.BLACK)
            bench.tick(tick_ms)

    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total_frames = sum(b.frame_count for b in benches)
    all_frame_bytes = [n for b in benches for n in b.frame_bytes]
    all_frame_events = [n for b in benches for n in b.frame_events]
    total_bytes = sum(all_frame_bytes)
    simulated_seconds_per_game = elapsed_ms / 1000

    return BenchResult(
        games=games,
        simulated_ms=elapsed_ms,
        total_frames=total_frames,
        frames_per_second_per_game=(
            total_frames / (games * simulated_seconds_per_game)
            if simulated_seconds_per_game
            else 0.0
        ),
        bytes_per_frame_p50=_percentile(all_frame_bytes, 0.50),
        bytes_per_frame_p99=_percentile(all_frame_bytes, 0.99),
        bytes_per_frame_mean=statistics.fmean(all_frame_bytes) if all_frame_bytes else 0.0,
        bytes_per_second_per_game=(
            total_bytes / (games * simulated_seconds_per_game)
            if simulated_seconds_per_game
            else 0.0
        ),
        events_per_frame_mean=(
            statistics.fmean(all_frame_events) if all_frame_events else 0.0
        ),
        tracemalloc_bytes_per_live_game=peak_bytes / games if games else 0.0,
        metrics=_metrics_summary(),
    )


def _print_report(result: BenchResult) -> None:
    print(f"games:                          {result.games}")
    print(f"simulated ms/game:              {result.simulated_ms}")
    print(f"total frames:                   {result.total_frames}")
    print(f"frames/s/game:                  {result.frames_per_second_per_game:.4f}")
    print(f"bytes/frame p50:                {result.bytes_per_frame_p50:.1f}")
    print(f"bytes/frame p99:                {result.bytes_per_frame_p99:.1f}")
    print(f"bytes/frame mean:               {result.bytes_per_frame_mean:.1f}")
    print(f"bytes/s/game:                   {result.bytes_per_second_per_game:.1f}")
    print(f"events/frame mean:              {result.events_per_frame_mean:.3f}")
    print(f"tracemalloc bytes/live game:    {result.tracemalloc_bytes_per_live_game:.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES)
    parser.add_argument("--command-interval-ms", type=int, default=DEFAULT_COMMAND_INTERVAL_MS)
    parser.add_argument("--max-game-ms", type=int, default=DEFAULT_MAX_GAME_MS)
    parser.add_argument("--tick-ms", type=int, default=TICK_MS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--json", type=str, default=None, help="path to write JSON results")
    args = parser.parse_args()

    result = run_bench(
        games=args.games,
        command_interval_ms=args.command_interval_ms,
        max_game_ms=args.max_game_ms,
        tick_ms=args.tick_ms,
        seed=args.seed,
    )
    _print_report(result)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
