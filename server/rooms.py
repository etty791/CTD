"""Room membership and ELO matchmaking.

Two ways into a game:
  * explicit rooms — `create_room` mints a short, typeable room id (creator =
    White); others `join(room_id)` (second = Black, later joiners = observers).
  * matchmaking — `seek(rating)` pools a player and pairs them with a waiting
    seeker within ``MATCH_ELO_RANGE``, auto-creating a seated room on a match.

This module is pure and synchronous: it owns membership and the seek pool but
performs no I/O. The 1-minute seek timeout and every "opponent left" / "no
match" broadcast belong to the async handler layer, which drives them off the
results returned here (`SeekResult`, `LeaveResult`) and `cancel_seek`.

Role (PLAYER/OBSERVER) and Color (WHITE/BLACK) stay separate concepts; a join
result carries both, matching GameStartPayload(role, color).
"""

import secrets
from dataclasses import dataclass, field

from model.piece import Color
from server.server_config import (
    MATCH_ELO_RANGE,
    MAX_PLAYERS_PER_ROOM,
    ROOM_ID_ALPHABET,
    ROOM_ID_LENGTH,
    SEAT_COLORS,
)
from shared.protocol_config import Role
from server.session import PlayerSession


@dataclass
class Room:
    name: str  # the short room id
    players: list[PlayerSession] = field(default_factory=list)
    observers: list[PlayerSession] = field(default_factory=list)
    game_id: str | None = None


@dataclass(frozen=True)
class RoomJoinResult:
    role: Role
    color: Color | None
    room: Room
    should_start_game: bool


@dataclass(frozen=True)
class LeaveResult:
    """What `leave` did, so the handler knows whom to notify.

    `role` is the seat the departing session held (PLAYER/OBSERVER), or None if
    it was not in any room. `remaining_*` list who is still in the room after
    the removal (empty when the room was closed).
    """

    role: Role | None
    room: Room | None
    room_closed: bool
    remaining_players: tuple[PlayerSession, ...]
    remaining_observers: tuple[PlayerSession, ...]


@dataclass(frozen=True)
class SeekResult:
    """Outcome of a matchmaking `seek`. When `matched`, `room` holds both
    players seated (index 0 White, index 1 Black) and the game should start."""

    matched: bool
    room: Room | None


@dataclass
class _Seeker:
    session: PlayerSession
    rating: int


class UnknownRoomError(Exception):
    """Raised when a join targets a room id that does not exist."""

    def __init__(self, room_id: str):
        super().__init__(f"no room with id {room_id!r}")
        self.room_id = room_id


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._player_to_room: dict[str, str] = {}
        self._seekers: list[_Seeker] = []

    # --- room construction / seating ---
    def _generate_room_id(self) -> str:
        while True:
            room_id = "".join(
                secrets.choice(ROOM_ID_ALPHABET) for _ in range(ROOM_ID_LENGTH)
            )
            if room_id not in self._rooms:
                return room_id

    def _new_room(self) -> Room:
        room = Room(name=self._generate_room_id())
        self._rooms[room.name] = room
        return room

    def _seat_player(self, room: Room, session: PlayerSession) -> Color:
        color = SEAT_COLORS[len(room.players)]
        room.players.append(session)
        self._player_to_room[session.player_id] = room.name
        return color

    # --- explicit rooms ---
    def create_room(self, session: PlayerSession) -> RoomJoinResult:
        room = self._new_room()
        color = self._seat_player(room, session)  # White
        return RoomJoinResult(
            role=Role.PLAYER, color=color, room=room, should_start_game=False
        )

    def room_exists(self, room_id: str) -> bool:
        return room_id in self._rooms

    def join(self, room_id: str, session: PlayerSession) -> RoomJoinResult:
        room = self._rooms.get(room_id)
        if room is None:
            raise UnknownRoomError(room_id)

        joinable = room.game_id is None and len(room.players) < MAX_PLAYERS_PER_ROOM
        if not joinable:
            room.observers.append(session)
            self._player_to_room[session.player_id] = room_id
            return RoomJoinResult(
                role=Role.OBSERVER, color=None, room=room, should_start_game=False
            )

        color = self._seat_player(room, session)
        should_start_game = len(room.players) == MAX_PLAYERS_PER_ROOM
        return RoomJoinResult(
            role=Role.PLAYER,
            color=color,
            room=room,
            should_start_game=should_start_game,
        )

    # --- matchmaking ---
    def seek(self, session: PlayerSession, rating: int) -> SeekResult:
        opponent = self._find_opponent(rating)
        if opponent is None:
            self._seekers.append(_Seeker(session=session, rating=rating))
            return SeekResult(matched=False, room=None)

        self._seekers.remove(opponent)
        room = self._new_room()
        self._seat_player(room, opponent.session)  # waited first -> White
        self._seat_player(room, session)  # caller -> Black
        return SeekResult(matched=True, room=room)

    def _find_opponent(self, rating: int) -> _Seeker | None:
        in_range = [
            seeker
            for seeker in self._seekers
            if abs(seeker.rating - rating) <= MATCH_ELO_RANGE
        ]
        if not in_range:
            return None
        return min(in_range, key=lambda seeker: abs(seeker.rating - rating))

    def cancel_seek(self, session: PlayerSession) -> bool:
        for seeker in self._seekers:
            if seeker.session is session:
                self._seekers.remove(seeker)
                return True
        return False

    # --- leaving ---
    def leave(self, session: PlayerSession) -> LeaveResult:
        self.cancel_seek(session)

        name = self._player_to_room.pop(session.player_id, None)
        room = self._rooms.get(name) if name is not None else None
        if room is None:
            return LeaveResult(
                role=None,
                room=None,
                room_closed=False,
                remaining_players=(),
                remaining_observers=(),
            )

        role: Role | None = None
        if session in room.players:
            room.players.remove(session)
            role = Role.PLAYER
        elif session in room.observers:
            room.observers.remove(session)
            role = Role.OBSERVER

        room_closed = not room.players and not room.observers
        if room_closed:
            self.close_room(name)

        return LeaveResult(
            role=role,
            room=room,
            room_closed=room_closed,
            remaining_players=tuple(room.players),
            remaining_observers=tuple(room.observers),
        )

    def room_of(self, player_id: str) -> Room | None:
        name = self._player_to_room.get(player_id)
        return self._rooms.get(name) if name is not None else None

    def close_room(self, name: str) -> None:
        self._rooms.pop(name, None)
