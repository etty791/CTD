"""A single live game: two players, optional observers, server-side ticking,
and the game-end -> Elo -> GAME_OVER pipeline.

Layering: GameSession must NOT know about GameRegistry or RoomManager. Registry
and room cleanup are injected as the async `on_finalize` callback, invoked once
at the very end of `_finalize`.

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
from events.game_events import GameEnded
from model.piece import Color
from server.async_clock import AsyncClock, TimerHandle
from server.encoding import state_payload_from_snapshot
from shared.messages import (
    GameOverPayload,
    RatingChangePayload,
)
from server.persistence.worker import PersistenceWorker
from shared.protocol import Envelope, MessageType
from server.server_config import GAME_OVER_REASON_KING_CAPTURED
from server.session import PlayerSession

logger = logging.getLogger(__name__)

FinalizeCallback = Callable[["GameSession"], Awaitable[None]]


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

    async def broadcast_state(self) -> None:
        state_payload = state_payload_from_snapshot(self.engine.get_snapshot())
        envelope = Envelope(
            type=MessageType.STATE,
            payload=state_payload.model_dump(),
            game_id=self.id,
        )
        for session in self._recipients():
            await session.connection.send(envelope)

    # --- ticking ----------------------------------------------------------

    def start_ticking(self) -> None:
        self._tick_handle = self._clock.every(self._on_tick)

    def _on_tick(self, elapsed_ms: int) -> None:
        # Runs synchronously on the clock callback. engine.wait may publish
        # GameEnded, which invokes _on_game_ended synchronously right here.
        self.engine.wait(elapsed_ms)
        asyncio.create_task(self.broadcast_state())
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
        envelope = Envelope(
            type=MessageType.GAME_OVER,
            payload=payload.model_dump(),
            game_id=self.id,
        )
        for session in self._recipients():
            await session.connection.send(envelope)

        if self._on_finalize is not None:
            await self._on_finalize(self)
