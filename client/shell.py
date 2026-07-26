"""Shell: dispatch-dict REPL (register/login/play/room/help/quit) that hands
off to the OpenCV GUI once a game starts, mirroring the dispatch-dict pattern
in textTester/script_runner.py."""

import getpass

from client.client_config import (
    CMD_HELP,
    CMD_LOGIN,
    CMD_PLAY,
    CMD_QUIT,
    CMD_REGISTER,
    CMD_ROOM,
    MATCHMAKING_TIMEOUT_BUFFER_S,
    MSG_GOODBYE,
    MSG_HELP_TEXT,
    MSG_NOT_LOGGED_IN,
    MSG_SEARCHING,
    MSG_SEEK_CANCELLED,
    MSG_UNKNOWN_COMMAND,
    MSG_WAITING_FOR_OPPONENT,
    PASSWORD_PROMPT,
    PROMPT,
    RESPONSE_TIMEOUT_S,
    USERNAME_PROMPT,
)
from client.network import ServerConnection
from client.remote_game import RemoteGame
from shared.messages import (
    AuthAckPayload,
    CredentialsPayload,
    ErrorPayload,
    GameStartPayload,
    JoinRoomPayload,
    RoomWaitingPayload,
)
from shared.protocol import Envelope, MessageType
from shared.protocol_config import MATCH_TIMEOUT_MS, Role
from view.GUI_runner import run_GUI


class Shell:
    def __init__(self, connection: ServerConnection):
        self.connection = connection
        self.username: str | None = None
        self.rating: int | None = None
        self._commands = {
            CMD_REGISTER: self._cmd_register,
            CMD_LOGIN: self._cmd_login,
            CMD_PLAY: self._cmd_play,
            CMD_ROOM: self._cmd_room,
            CMD_HELP: self._cmd_help,
            CMD_QUIT: self._cmd_quit,
        }
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                self._cmd_quit("")
                break
            if not line:
                continue
            command, _, rest = line.partition(" ")
            handler = self._commands.get(command)
            if handler is None:
                print(MSG_UNKNOWN_COMMAND)
                continue
            handler(rest.strip())

    # --- commands -----------------------------------------------------

    def _cmd_register(self, _args: str) -> None:
        username = input(USERNAME_PROMPT)
        password = getpass.getpass(PASSWORD_PROMPT)
        self.connection.send(
            Envelope(
                type=MessageType.REGISTER,
                payload=CredentialsPayload(username=username, password=password).model_dump(),
            )
        )
        envelope = self.connection.wait_for({MessageType.REGISTER}, RESPONSE_TIMEOUT_S)
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        print(f"Registered {username}. You can now log in.")

    def _cmd_login(self, _args: str) -> None:
        username = input(USERNAME_PROMPT)
        password = getpass.getpass(PASSWORD_PROMPT)
        self.connection.send(
            Envelope(
                type=MessageType.LOGIN,
                payload=CredentialsPayload(username=username, password=password).model_dump(),
            )
        )
        envelope = self.connection.wait_for({MessageType.LOGIN}, RESPONSE_TIMEOUT_S)
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        ack = AuthAckPayload.model_validate(envelope.payload)
        self.username = ack.player_id
        self.rating = ack.rating
        print(f"Logged in as {self.username} (rating {self.rating})")

    def _cmd_play(self, _args: str) -> None:
        if self.username is None:
            print(MSG_NOT_LOGGED_IN)
            return
        self.connection.send(Envelope(type=MessageType.PLAY, payload={}))
        print(MSG_SEARCHING)
        timeout = MATCH_TIMEOUT_MS / 1000 + MATCHMAKING_TIMEOUT_BUFFER_S
        envelope = self.connection.wait_for({MessageType.GAME_START}, timeout)
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        self._enter_game(envelope)

    def _cmd_room(self, args: str) -> None:
        if self.username is None:
            print(MSG_NOT_LOGGED_IN)
            return
        room_id = args.strip()
        if not room_id:
            self._create_room()
        else:
            self._join_room(room_id)

    def _create_room(self) -> None:
        self.connection.send(Envelope(type=MessageType.CREATE_ROOM, payload={}))
        envelope = self.connection.wait_for({MessageType.CREATE_ROOM}, RESPONSE_TIMEOUT_S)
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        waiting = RoomWaitingPayload.model_validate(envelope.payload)
        print(f"Room created: {waiting.room_id} -- share this id with your opponent. "
              f"{MSG_WAITING_FOR_OPPONENT}")
        try:
            envelope = self.connection.wait_for({MessageType.GAME_START}, timeout=None)
        except KeyboardInterrupt:
            print(MSG_SEEK_CANCELLED)
            return
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        self._enter_game(envelope)

    def _join_room(self, room_id: str) -> None:
        self.connection.send(
            Envelope(
                type=MessageType.JOIN_ROOM,
                payload=JoinRoomPayload(room_id=room_id).model_dump(),
            )
        )
        envelope = self.connection.wait_for(
            {MessageType.GAME_START, MessageType.JOIN_ROOM}, RESPONSE_TIMEOUT_S
        )
        if envelope.type == MessageType.ERROR:
            print(ErrorPayload.model_validate(envelope.payload).message)
            return
        if envelope.type == MessageType.JOIN_ROOM:
            print(MSG_WAITING_FOR_OPPONENT)
            try:
                envelope = self.connection.wait_for({MessageType.GAME_START}, timeout=None)
            except KeyboardInterrupt:
                print(MSG_SEEK_CANCELLED)
                return
            if envelope.type == MessageType.ERROR:
                print(ErrorPayload.model_validate(envelope.payload).message)
                return
        self._enter_game(envelope)

    def _enter_game(self, envelope: Envelope) -> None:
        payload = GameStartPayload.model_validate(envelope.payload)
        is_observer = payload.role == Role.OBSERVER.value
        remote_game = RemoteGame(self.connection, is_observer)
        self.connection.set_active_game(remote_game)
        role_desc = "observing" if is_observer else payload.color
        print(f"Game starting -- you are {role_desc}")

        run_GUI(remote_game)  # blocks on the main thread until the window is closed

        self.connection.set_active_game(None)
        self._report_outcome(remote_game)

    def _report_outcome(self, remote_game: RemoteGame) -> None:
        payload = remote_game.game_over_payload
        if payload is None:
            print("Game ended without a result (connection dropped?).")
            return
        print(f"Game over -- winner: {payload.winner} ({payload.reason})")
        for change in payload.rating_changes:
            if change.username == self.username:
                self.rating = change.new_rating
                delta = change.new_rating - change.old_rating
                sign = "+" if delta >= 0 else ""
                print(f"Rating: {change.old_rating} -> {change.new_rating} ({sign}{delta})")

    def _cmd_help(self, _args: str) -> None:
        print(MSG_HELP_TEXT)

    def _cmd_quit(self, _args: str) -> None:
        print(MSG_GOODBYE)
        self.connection.close()
        self._running = False
