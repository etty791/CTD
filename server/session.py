from server.connection import Connection


class PlayerSession:
    def __init__(self, player_id: str, connection: Connection):
        self.player_id = player_id
        self.connection = connection
        connection.player_session = self
