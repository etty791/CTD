"""A single live game: two players, optional observers, server-side ticking,
and the game-end -> Elo -> GAME_OVER pipeline.

Layering: GameSession must NOT know about GameRegistry or RoomManager. Registry
and room cleanup are injected as the async `on_finalize` callback, invoked once
at the very end of `_finalize`.

Broadcasting is event-driven, not tick-driven: the engine still advances real
time every TICK_MS (arrivals, path collisions and rest expiry all need it), but
a frame goes out only when one of STATE_CHANGING_EVENTS was published during
that tick - every event in a tick coalescing into a single DELTA frame. An idle
game sends nothing at all; there is no heartbeat, because a client that misses
a frame sees the gap in Envelope.seq and asks for a keyframe. Clients
interpolate moving pieces themselves from absolute move times, so they do not
need a fresh sample every tick to animate smoothly.

Two frame types, one sequence: DELTA advances `_seq` by one, KEYFRAME restates
the whole game at whatever `_seq` currently is (so a keyframe can be sent to
one recipient without disturbing the shared stream). Every recovery path -
game start, observer join, RESYNC - ends in the same keyframe.

End-of-game state machine (two idempotent gates):
- `_ended`   — set the first time the game concludes (king capture via a
  GameEnded bus event, or a forfeit). Guards against GameEnded's *double*
  publish so exactly one Elo job is submitted.
- `_finalized` — set the first time `_finalize` runs, so the GAME_OVER
  broadcast + cleanup happen exactly once even if capture and forfeit race.
"""

import asyncio
import logging
import uuid
from concurrent.futures import Future
from typing import Awaitable, Callable, Optional

from game_engine.game import KungFuChessGame
from events.game_events import (
    GameEnded,
    MoveAborted,
    MoveCompleted,
    MoveStarted,
    MoveTruncated,
    PieceCaptured,
    RestEnded,
)
from model.piece import Color
from observability.metrics import counter, histogram
from observability.metrics_config import (
    GAME_EVENTS_PER_FRAME,
    GAME_FRAMES_TOTAL,
)
from server.async_clock import AsyncClock, TimerHandle
from server.delta import DeltaBuilder
from server.encoding import keyframe_payload_from_snapshot
from shared.messages import (
    DeltaPayload,
    GameOverPayload,
    RatingChangePayload,
)
from server.persistence.worker import PersistenceWorker
from shared.protocol import Envelope, MessageType
from server.server_config import FRAME_MIN_INTERVAL_MS, GAME_OVER_REASON_KING_CAPTURED
from server.session import PlayerSession

logger = logging.getLogger(__name__)

FinalizeCallback = Callable[["GameSession"], Awaitable[None]]

# Every event that makes the board look different to a client. The engine's
# bus is the session's only notion of "something happened": a tick that
# publishes none of these broadcasts nothing.
STATE_CHANGING_EVENTS = (
    MoveStarted,
    MoveCompleted,
    MoveTruncated,
    MoveAborted,
    PieceCaptured,
    RestEnded,
    GameEnded,
)

_game_frames_total = counter(GAME_FRAMES_TOTAL)
_game_events_per_frame = histogram(GAME_EVENTS_PER_FRAME)

# The stream starts before any frame has been sent, so the first DELTA is 1.
INITIAL_SEQ = 0


class GameSession:
    def __init__(
        self,
        player_a: PlayerSession,
        player_b: PlayerSession,
        clock: AsyncClock,
        persistence: PersistenceWorker,
        room_id: str,
        on_finalize: Optional[FinalizeCallback] = None,
    ):
        self.id: str = str(uuid.uuid4())
        self.engine = KungFuChessGame()
        # GameStarted already fired inside the engine's __init__; GameEnded fires
        # later inside engine.wait(), so subscribing here is safe (and needed).
        self.engine.events.subscribe(GameEnded, self._on_game_ended)
        self._delta = DeltaBuilder(self._read_scores)
        for event_type in STATE_CHANGING_EVENTS:
            self.engine.events.subscribe(event_type, self._delta.on_event)

        self.players: dict[str, PlayerSession] = {
            player_a.player_id: player_a,
            player_b.player_id: player_b,
        }
        self.color_of: dict[str, Color] = {
            player_a.player_id: Color.WHITE,
            player_b.player_id: Color.BLACK,
        }
        self.observers: list[PlayerSession] = []
        self.room_id = room_id

        self._clock = clock
        self._persistence = persistence
        self._on_finalize = on_finalize

        self._seq = INITIAL_SEQ
        self._last_frame_ms: int | None = None
        self._ended = False
        self._finalized = False
        self._winner: Color | None = None
        self._elo_future: Future | None = None
        self._tick_handle: TimerHandle | None = None

    # --- membership -------------------------------------------------------

    def opponent_of(self, player_id: str) -> PlayerSession:
        other_id = next(pid for pid in self.players if pid != player_id)
        return self.players[other_id]

    def username_of_color(self, color: Color) -> str:
        return next(pid for pid, c in self.color_of.items() if c == color)

    def add_observer(self, session: PlayerSession) -> None:
        self.observers.append(session)

    def remove_observer(self, session: PlayerSession) -> None:
        if session in self.observers:
            self.observers.remove(session)

    def _recipients(self) -> list[PlayerSession]:
        return [*self.players.values(), *self.observers]

    # --- broadcasting -----------------------------------------------------

    def _read_scores(self) -> dict[Color, int]:
        return self.engine.get_snapshot().get_scores()

    def keyframe_envelope(self) -> Envelope:
        """The whole game at the current sequence number. Sending one costs
        no sequence number of its own, so a personal keyframe (observer join,
        RESYNC) leaves the shared delta stream untouched."""
        payload = keyframe_payload_from_snapshot(self.engine.get_snapshot())
        return Envelope(
            type=MessageType.KEYFRAME,
            payload=payload.model_dump(),
            game_id=self.id,
            seq=self._seq,
        )

    async def _fan_out(self, envelope: Envelope) -> None:
        """Serialize once, send to everyone. One half-closed socket must not
        starve the recipients behind it, hence return_exceptions."""
        body = envelope.model_dump_json()
        await asyncio.gather(
            *(
                session.connection.send_raw(body, envelope.type)
                for session in self._recipients()
            ),
            return_exceptions=True,
        )

    async def broadcast_keyframe(self) -> None:
        _game_frames_total.inc()
        await self._fan_out(self.keyframe_envelope())

    def _frame_capped(self) -> bool:
        """True if a frame went out less than FRAME_MIN_INTERVAL_MS ago. The
        ops stay buffered and go out with the next flush, so nothing is lost
        by waiting - only the tick-independent paths (a move echo) can ever
        arrive this fast."""
        now_ms = self._clock.now_ms()
        if self._last_frame_ms is not None and now_ms - self._last_frame_ms < FRAME_MIN_INTERVAL_MS:
            return True
        self._last_frame_ms = now_ms
        return False

    async def flush_frame(self) -> None:
        """Drain whatever the engine published into a single DELTA frame. An
        idle pass has nothing to say and sends nothing."""
        if not self._delta.has_ops() or self._frame_capped():
            return
        ops = self._delta.drain()
        self._seq += 1
        _game_frames_total.inc()
        _game_events_per_frame.observe(len(ops))
        payload = DeltaPayload(ops=ops, server_time_ms=self.engine.get_snapshot().get_clock_ms())
        await self._fan_out(
            Envelope(
                type=MessageType.DELTA,
                payload=payload.model_dump(),
                game_id=self.id,
                seq=self._seq,
            )
        )

    # --- ticking ----------------------------------------------------------

    def start_ticking(self) -> None:
        self._tick_handle = self._clock.every(self._on_tick)

    def _on_tick(self, elapsed_ms: int) -> None:
        # Runs synchronously on the clock callback. engine.wait may publish
        # GameEnded, which invokes _on_game_ended synchronously right here -
        # as it does DeltaBuilder.on_event for every state-changing event.
        self.engine.wait(elapsed_ms)
        if self._delta.has_ops():
            asyncio.create_task(self.flush_frame())
        if not self.engine.game_active:
            self.cancel_ticking()
            asyncio.create_task(self._finalize(GAME_OVER_REASON_KING_CAPTURED))

    def cancel_ticking(self) -> None:
        if self._tick_handle is not None:
            self._tick_handle.cancel()
            self._tick_handle = None

    # --- end-of-game ------------------------------------------------------

    def _submit_elo(self, winner: Color) -> None:
        self._elo_future = self._persistence.submit(
            lambda repo: repo.apply_game_result(
                self.username_of_color(Color.WHITE),
                self.username_of_color(Color.BLACK),
                winner,
            )
        )

    def _on_game_ended(self, event: GameEnded) -> None:
        # SYNC bus handler. Idempotent: the arbiter publishes GameEnded up to
        # twice (path-collision + arrival); the _ended gate keeps Elo to one job.
        if self._ended:
            return
        self._ended = True
        self._winner = event.winner
        self._submit_elo(event.winner)

    async def finalize_by_forfeit(self, winner_color: Color, reason: str) -> None:
        if self._ended or self._finalized:
            return
        self.cancel_ticking()
        self.engine.finish_game()
        self._ended = True
        self._winner = winner_color
        self._submit_elo(winner_color)
        await self._finalize(reason)

    async def _finalize(self, reason: str) -> None:
        if self._finalized:
            return
        self._finalized = True

        rating_changes: list[RatingChangePayload] = []
        if self._elo_future is not None:
            try:
                ratings = await asyncio.wrap_future(self._elo_future)
            except Exception:
                logger.exception("Elo update failed for game %s", self.id)
            else:
                white_username = self.username_of_color(Color.WHITE)
                black_username = self.username_of_color(Color.BLACK)
                rating_changes = [
                    RatingChangePayload(
                        username=white_username,
                        old_rating=ratings.white_old,
                        new_rating=ratings.white_new,
                    ),
                    RatingChangePayload(
                        username=black_username,
                        old_rating=ratings.black_old,
                        new_rating=ratings.black_new,
                    ),
                ]

        payload = GameOverPayload(
            winner=self._winner.value,
            reason=reason,
            rating_changes=rating_changes,
        )
        await self._fan_out(
            Envelope(
                type=MessageType.GAME_OVER,
                payload=payload.model_dump(),
                game_id=self.id,
            )
        )

        if self._on_finalize is not None:
            await self._on_finalize(self)
