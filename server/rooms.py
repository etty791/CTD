"""Room membership and ELO matchmaking.

Two ways into a game:
  * explicit rooms — `create_room` mints a typeable room id (creator =
    White); others `join(room_id)` (second = Black, later joiners = observers).
  * matchmaking — `seek(rating, now_ms)` pools a player and pairs them with a
    waiting seeker within a widening rating band, auto-creating a seated room
    on a match.

This module is pure and synchronous: it owns membership and the seek pool but
performs no I/O and reads no real clock - `seek` takes `now_ms` as a plain
argument so callers (and tests) supply time explicitly. The 1-minute seek
timeout and every "opponent left" / "no match" broadcast belong to the async
handler layer, which drives them off the results returned here (`SeekResult`,
`LeaveResult`) and `cancel_seek`.

Widening is evaluated only when a new seeker arrives, against however long
the *waiting* seeker has been queued - two seekers who arrive together and
sit outside each other's initial band never get a second look at each other;
they only ever re-pair if a third seeker's arrival triggers a fresh check.
The `MATCH_TIMEOUT_MS` giving-up path (handler layer) is unaffected by this.

Rooms move through a one-way `RoomStatus` state machine: WAITING -> LIVE ->
ENDED (`mark_live`/`mark_ended`). `join` is idempotent with respect to a
caller's existing seat: a repeat claim by an already-seated player returns
their existing seat rather than re-seating them, and a spectator is never
promoted to a player even if a seat has since freed up (spec §7). In this
single-threaded manager the claim is trivially atomic; a distributed version
swaps the same predicate for e.g. Redis HSETNX without changing callers.

Role (PLAYER/OBSERVER) and Color (WHITE/BLACK) stay separate concepts; a join
result carries both, matching GameStartPayload(role, color).
"""

import secrets
from dataclasses import dataclass, field

from model.piece import Color
from server.server_config import (
    MATCH_ELO_RANGE_INITIAL,
    MATCH_ELO_RANGE_MAX,
    MATCH_ELO_RANGE_STEP,
    MATCH_ELO_WIDEN_INTERVAL_MS,
    MAX_PLAYERS_PER_ROOM,
    ROOM_ID_ALPHABET,
    ROOM_ID_LENGTH,
    SEAT_COLORS,
)
from shared.protocol_config import Role, RoomStatus
from server.session import PlayerSession


@dataclass
class Room:
    name: str  # the room id
    players: list[PlayerSession] = field(default_factory=list)
    observers: list[PlayerSession] = field(default_factory=list)
    game_id: str | None = None
    status: RoomStatus = RoomStatus.WAITING


@dataclass(frozen=True)
class RoomJoinResult:
    role: Role
    color: Color | None
    room: Room
    should_start_game: bool


@dataclass(frozen=True)
class LeaveResult:
    """What `leave` did, so the handler knows whom to notify."""

    room: Room | None
    room_closed: bool


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
    queued_at_ms: int


class UnknownRoomError(Exception):
    """Raised when a join targets a room id that does not exist."""

    def __init__(self, room_id: str):
        super().__init__(f"no room with id {room_id!r}")
        self.room_id = room_id


class InvalidRoomTransitionError(Exception):
    """Raised on an illegal RoomStatus transition (the FSM is one-way:
    WAITING -> LIVE -> ENDED)."""

    def __init__(self, room_id: str, from_status: RoomStatus, to_status: RoomStatus):
        super().__init__(
            f"room {room_id!r} cannot go from {from_status} to {to_status}"
        )
        self.room_id = room_id
        self.from_status = from_status
        self.to_status = to_status


def _band_for(queued_at_ms: int, now_ms: int) -> int:
    """Rating band a seeker has widened to after waiting `now_ms -
    queued_at_ms`: MATCH_ELO_RANGE_INITIAL to start, +MATCH_ELO_RANGE_STEP
    every MATCH_ELO_WIDEN_INTERVAL_MS, capped at MATCH_ELO_RANGE_MAX."""
    waited_ms = max(0, now_ms - queued_at_ms)
    widened = MATCH_ELO_RANGE_INITIAL + MATCH_ELO_RANGE_STEP * (
        waited_ms // MATCH_ELO_WIDEN_INTERVAL_MS
    )
    return min(widened, MATCH_ELO_RANGE_MAX)


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

        # Idempotent claim: a repeat join by an already-seated player returns
        # their existing seat rather than re-seating them, and a spectator is
        # never promoted to a player even if a seat has since freed up.
        for player in room.players:
            if player.player_id == session.player_id:
                return RoomJoinResult(
                    role=Role.PLAYER,
                    color=self.color_of(room, player),
                    room=room,
                    should_start_game=False,
                )
        for observer in room.observers:
            if observer.player_id == session.player_id:
                return RoomJoinResult(
                    role=Role.OBSERVER, color=None, room=room, should_start_game=False
                )

        joinable = room.status is RoomStatus.WAITING and len(room.players) < MAX_PLAYERS_PER_ROOM
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

    @staticmethod
    def color_of(room: Room, player: PlayerSession) -> Color:
        return SEAT_COLORS[room.players.index(player)]

    def mark_live(self, room: Room, game_id: str) -> None:
        if room.status is not RoomStatus.WAITING:
            raise InvalidRoomTransitionError(room.name, room.status, RoomStatus.LIVE)
        room.status = RoomStatus.LIVE
        room.game_id = game_id

    def mark_ended(self, room: Room) -> None:
        if room.status is not RoomStatus.LIVE:
            raise InvalidRoomTransitionError(room.name, room.status, RoomStatus.ENDED)
        room.status = RoomStatus.ENDED

    # --- matchmaking ---
    def seek(self, session: PlayerSession, rating: int, now_ms: int) -> SeekResult:
        opponent = self._find_opponent(rating, now_ms)
        if opponent is None:
            self._seekers.append(_Seeker(session=session, rating=rating, queued_at_ms=now_ms))
            return SeekResult(matched=False, room=None)

        self._seekers.remove(opponent)
        room = self._new_room()
        self._seat_player(room, opponent.session)  # waited first -> White
        self._seat_player(room, session)  # caller -> Black
        return SeekResult(matched=True, room=room)

    def _find_opponent(self, rating: int, now_ms: int) -> _Seeker | None:
        in_range = [
            seeker
            for seeker in self._seekers
            if abs(seeker.rating - rating) <= _band_for(seeker.queued_at_ms, now_ms)
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
            return LeaveResult(room=None, room_closed=False)

        if session in room.players:
            room.players.remove(session)
        elif session in room.observers:
            room.observers.remove(session)

        room_closed = not room.players and not room.observers
        if room_closed:
            self.close_room(name)

        return LeaveResult(room=room, room_closed=room_closed)

    def room_of(self, player_id: str) -> Room | None:
        name = self._player_to_room.get(player_id)
        return self._rooms.get(name) if name is not None else None

    def close_room(self, name: str) -> None:
        self._rooms.pop(name, None)
