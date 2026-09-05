from typing import Optional

from server.async_clock import AsyncClock
from server.game_session import FinalizeCallback, GameSession
from server.persistence.worker import PersistenceWorker
from server.session import PlayerSession


class GameRegistry:
    def __init__(self):
        self._games: dict[str, GameSession] = {}
        self._player_to_game: dict[str, str] = {}

    def create_game(
        self,
        player_a: PlayerSession,
        player_b: PlayerSession,
        clock: AsyncClock,
        persistence: PersistenceWorker,
        room_id: str,
        on_finalize: Optional[FinalizeCallback] = None,
    ) -> GameSession:
        game = GameSession(
            player_a, player_b, clock, persistence, room_id, on_finalize
        )
        self._games[game.id] = game
        self._player_to_game[player_a.player_id] = game.id
        self._player_to_game[player_b.player_id] = game.id
        game.start_ticking()
        return game

    def get(self, game_id: str) -> GameSession | None:
        return self._games.get(game_id)

    def get_game_for_player(self, player_id: str) -> GameSession | None:
        game_id = self._player_to_game.get(player_id)
        return self._games.get(game_id) if game_id else None

    def add_observer(self, game_id: str, player_id: str) -> None:
        """Track an observer's mapping too, so get_game_for_player resolves
        them (e.g. for the observer-cannot-move check). GameSession itself
        must not know about the registry, so callers of game.add_observer
        are expected to call this alongside it."""
        self._player_to_game[player_id] = game_id

    def remove_player_mapping(self, player_id: str) -> None:
        """Drop a single player_id -> game_id mapping, e.g. an observer who
        left mid-game (without ending it)."""
        self._player_to_game.pop(player_id, None)

    def remove(self, game_id: str) -> None:
        game = self._games.pop(game_id, None)
        if game:
            game.cancel_ticking()  # defensive: stop the loop if still live
            observer_ids = [session.player_id for session in game.observers]
            for pid in list(game.players) + observer_ids:
                self._player_to_game.pop(pid, None)
