from server.connection import Connection


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, Connection] = {}

    def register(self, connection: Connection) -> None:
        self._connections[connection.id] = connection

    def remove(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    def get(self, connection_id: str) -> Connection | None:
        return self._connections.get(connection_id)

    def count(self) -> int:
        return len(self._connections)
