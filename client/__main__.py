from client.client_config import resolve_server_url
from client.network import ServerConnection
from client.shell import Shell


def main() -> None:
    connection = ServerConnection(resolve_server_url())
    connection.start()
    Shell(connection).run()


if __name__ == "__main__":
    main()
