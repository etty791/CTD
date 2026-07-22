from server.game_session import GameSession
from server.session import PlayerSession


class GameRegistry:
    def __init__(self):
        self._games: dict[str, GameSession] = {}
        self._player_to_game: dict[str, str] = {}

    def create_game(self, player_a: PlayerSession, player_b: PlayerSession) -> GameSession:
        game = GameSession(player_a, player_b)
        self._games[game.id] = game
        self._player_to_game[player_a.player_id] = game.id
        self._player_to_game[player_b.player_id] = game.id
        return game

    def get(self, game_id: str) -> GameSession | None:
        return self._games.get(game_id)

    def get_game_for_player(self, player_id: str) -> GameSession | None:
        game_id = self._player_to_game.get(player_id)
        return self._games.get(game_id) if game_id else None

    def remove(self, game_id: str) -> None:
        game = self._games.pop(game_id, None)
        if game:
            for pid in game.players:
                self._player_to_game.pop(pid, None)
