import dataclasses
import uuid

from game_engine.game import KungFuChessGame
from model.piece import Color
from server.protocol import Envelope, MessageType
from server.session import PlayerSession


class GameSession:
    def __init__(self, player_a: PlayerSession, player_b: PlayerSession):
        self.id: str = str(uuid.uuid4())
        self.engine = KungFuChessGame()
        self.players: dict[str, PlayerSession] = {
            player_a.player_id: player_a,
            player_b.player_id: player_b,
        }
        self.color_of: dict[str, Color] = {
            player_a.player_id: Color.WHITE,
            player_b.player_id: Color.BLACK,
        }

    def opponent_of(self, player_id: str) -> PlayerSession:
        other_id = next(pid for pid in self.players if pid != player_id)
        return self.players[other_id]

    async def broadcast_state(self) -> None:
        state_payload = self.engine.get_snapshot().to_payload()
        #TODO: understand exactly what is sent here
        envelope = Envelope(type=MessageType.STATE, payload=dataclasses.asdict(state_payload), game_id=self.id)
        for session in self.players.values():
            await session.connection.send(envelope)
