import asyncio
from concurrent.futures import Future

from events.game_events import GameEnded, MoveStarted, PieceCaptured
from model.piece import Color, PieceType
from model.position import Position
from real_time.real_time_config import DEFAULT_MOVE_DELAY_MS, LONG_REST_DURATION_MS
from server.game_registry import GameRegistry
from server.game_session import GameSession
from server.persistence.user_repository import GameResultRatings
from shared.protocol import Envelope, MessageType
from server.server_config import (
    FRAME_MIN_INTERVAL_MS,
    GAME_OVER_REASON_DISCONNECT,
    GAME_OVER_REASON_KING_CAPTURED,
    TICK_MS,
)
from server.session import PlayerSession
from shared.delta_ops import OpCode

# A one-square white pawn push on the standard starting board.
WHITE_PAWN_ORIGIN = Position(6, 0)
WHITE_PAWN_TARGET = Position(5, 0)
QUIET_TICKS = 20

PIECE_KEYS = {
    "id", "position", "type", "color", "state", "origin", "target",
    "move_start_ms", "move_arrival_ms",
}


class FakeConnection:
    def __init__(self):
        self.player_session = None
        self.sent: list[Envelope] = []

    async def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    async def send_raw(self, body: str, message_type) -> None:
        await self.send(Envelope.model_validate_json(body))


class FailingConnection:
    """A connection whose send always raises, simulating a half-closed
    socket -- used to prove one dead recipient can't blank a broadcast to
    everyone after it (§8.11)."""

    def __init__(self):
        self.player_session = None

    async def send(self, envelope: Envelope) -> None:
        raise RuntimeError("socket is closed")

    async def send_raw(self, body: str, message_type) -> None:
        raise RuntimeError("socket is closed")


class FakeHandle:
    def __init__(self):
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeClock:
    """Records the tick callback instead of spawning a real asyncio loop.
    `now` is advanced by the `tick` helper below, so the frame-emission cap
    (which measures real elapsed time) is under the test's control too."""

    def __init__(self):
        self.callback = None
        self.handle = FakeHandle()
        self.now = 0

    def every(self, callback):
        self.callback = callback
        return self.handle

    def now_ms(self) -> int:
        return self.now


class FakePersistence:
    """Records submissions; returns an already-completed Future."""

    def __init__(self, ratings: GameResultRatings | None = None):
        self.submissions: list = []
        self._ratings = ratings or GameResultRatings(
            white_old=1200, white_new=1216, black_old=1200, black_new=1184
        )

    def submit(self, fn) -> Future:
        self.submissions.append(fn)
        future: Future = Future()
        future.set_result(self._ratings)
        return future


class FailingPersistence:
    """Returns a Future whose result raises, simulating a broken Elo job."""

    def submit(self, fn) -> Future:
        future: Future = Future()
        future.set_exception(RuntimeError("db exploded"))
        return future


async def flush_tasks():
    """Deterministically run every task scheduled via create_task to completion."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def build_session(clock=None, persistence=None, on_finalize=None):
    conn_a, conn_b = FakeConnection(), FakeConnection()
    player_a = PlayerSession("white", conn_a)
    player_b = PlayerSession("black", conn_b)
    session = GameSession(
        player_a,
        player_b,
        clock or FakeClock(),
        persistence or FakePersistence(),
        room_id="room1",
        on_finalize=on_finalize,
    )
    return session, conn_a, conn_b


class TestBroadcastKeyframe:
    async def test_sends_a_keyframe_to_players_and_observers(self):
        session, conn_a, conn_b = build_session()
        obs_conn = FakeConnection()
        session.add_observer(PlayerSession("obs", obs_conn))

        await session.broadcast_keyframe()

        for conn in (conn_a, conn_b, obs_conn):
            assert len(conn.sent) == 1
            envelope = conn.sent[0]
            assert envelope.type == MessageType.KEYFRAME
            assert envelope.game_id == session.id
            assert set(envelope.payload.keys()) == {"pieces", "scores", "server_time_ms"}
            assert len(envelope.payload["pieces"]) == 32
            for piece in envelope.payload["pieces"]:
                assert set(piece.keys()) == PIECE_KEYS

    async def test_a_keyframe_does_not_consume_a_sequence_number(self):
        """A personal keyframe restates the stream where it already is, so
        the deltas either side of it stay contiguous for everybody else."""
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)
        await tick(clock, TICK_MS)
        seq_after_delta = delta_frames(conn_a)[-1].seq

        await session.broadcast_keyframe()

        assert conn_a.sent[-1].seq == seq_after_delta

    async def test_one_dead_recipient_does_not_blank_the_rest(self):
        """8.11: a bare send loop would let the first raise skip every later
        recipient. player_a's connection is half-closed; player_b and the
        observer must still get their frame."""
        conn_a, conn_b = FailingConnection(), FakeConnection()
        player_a = PlayerSession("white", conn_a)
        player_b = PlayerSession("black", conn_b)
        session = GameSession(
            player_a, player_b, FakeClock(), FakePersistence(), room_id="room1",
        )
        obs_conn = FakeConnection()
        session.add_observer(PlayerSession("obs", obs_conn))

        await session.broadcast_keyframe()

        assert len(conn_b.sent) == 1
        assert len(obs_conn.sent) == 1


class TestUsernameOfColor:
    def test_maps_colors_to_usernames(self):
        session, _, _ = build_session()
        assert session.username_of_color(Color.WHITE) == "white"
        assert session.username_of_color(Color.BLACK) == "black"


class TestGameEndedIdempotency:
    def test_double_publish_submits_elo_once(self):
        persistence = FakePersistence()
        session, _, _ = build_session(persistence=persistence)

        session.engine.events.publish(GameEnded(Color.WHITE))
        session.engine.events.publish(GameEnded(Color.WHITE))

        assert len(persistence.submissions) == 1
        assert session._winner == Color.WHITE


def delta_frames(conn: FakeConnection) -> list[Envelope]:
    return [envelope for envelope in conn.sent if envelope.type == MessageType.DELTA]


def op_codes(envelope: Envelope) -> list[str]:
    return [op[0] for op in envelope.payload["ops"]]


async def tick(clock: FakeClock, ms: int) -> None:
    clock.now += ms
    clock.callback(ms)
    await flush_tasks()


class TestDeltaFrames:
    """A frame goes out when the engine says something changed, never per
    tick -- and it carries the ops for what changed, not the whole board."""

    async def test_idle_ticks_send_nothing(self):
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()

        for _ in range(QUIET_TICKS):
            await tick(clock, TICK_MS)

        assert conn_a.sent == []

    async def test_a_started_move_makes_the_next_tick_send_one_delta(self):
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)

        await tick(clock, TICK_MS)

        frames = delta_frames(conn_a)
        assert len(frames) == 1
        assert op_codes(frames[0]) == [OpCode.MOVE_STARTED.value]

    async def test_sequence_numbers_are_contiguous(self):
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)
        await tick(clock, TICK_MS)
        await tick(clock, DEFAULT_MOVE_DELAY_MS)
        await tick(clock, LONG_REST_DURATION_MS)

        seqs = [envelope.seq for envelope in delta_frames(conn_a)]

        assert seqs == list(range(1, len(seqs) + 1))

    async def test_several_events_in_one_tick_cost_one_frame(self):
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)
        await tick(clock, TICK_MS)  # frame 1: the move started
        frames_after_start = len(delta_frames(conn_a))

        # One tick long enough to both land the move and expire its rest:
        # MoveCompleted + RestEnded, and still a single frame carrying both.
        await tick(clock, DEFAULT_MOVE_DELAY_MS + LONG_REST_DURATION_MS)

        frames = delta_frames(conn_a)
        assert len(frames) == frames_after_start + 1
        assert op_codes(frames[-1]) == [
            OpCode.MOVE_COMPLETED.value, OpCode.REST_ENDED.value
        ]

    async def test_a_quiet_board_gets_no_heartbeat_at_all(self):
        """An idle game emits zero frames. A dropped frame heals through
        seq-gap detection, so there is nothing left to heartbeat for."""
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()

        await tick(clock, TICK_MS * QUIET_TICKS)

        assert conn_a.sent == []

    async def test_frames_closer_than_the_cap_coalesce_without_losing_ops(self):
        """The 1-frame-per-10ms cap defers a flush rather than dropping it:
        the ops stay buffered and go out with the next one."""
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)
        await session.flush_frame()

        session.engine.jump_request(Position(6, 1))
        await session.flush_frame()          # inside the cap: deferred
        assert len(delta_frames(conn_a)) == 1

        clock.now += FRAME_MIN_INTERVAL_MS
        await session.flush_frame()

        frames = delta_frames(conn_a)
        assert len(frames) == 2
        assert op_codes(frames[1]) == [OpCode.MOVE_STARTED.value]

    async def test_a_capture_reports_the_score_change(self):
        clock = FakeClock()
        session, conn_a, _ = build_session(clock=clock)
        session.start_ticking()
        session.engine.events.publish(
            PieceCaptured(
                piece_id=3, piece_type=PieceType.PAWN, color=Color.BLACK,
                position=Position(4, 0), capturing_move_id=2,
            )
        )

        await tick(clock, TICK_MS)

        assert op_codes(delta_frames(conn_a)[-1]) == [
            OpCode.PIECE_CAPTURED.value, OpCode.SCORES.value
        ]

    async def test_one_dead_recipient_does_not_blank_the_rest(self):
        conn_a, conn_b = FailingConnection(), FakeConnection()
        clock = FakeClock()
        session = GameSession(
            PlayerSession("white", conn_a), PlayerSession("black", conn_b),
            clock, FakePersistence(), room_id="room1",
        )
        session.start_ticking()
        session.engine.move_request(WHITE_PAWN_ORIGIN, WHITE_PAWN_TARGET)

        await tick(clock, TICK_MS)

        assert len(delta_frames(conn_b)) == 1


class TestOnTick:
    async def test_tick_advances_engine_time(self):
        clock = FakeClock()
        session, _, _ = build_session(clock=clock)
        session.start_ticking()
        assert session.engine.rta.clock == 0

        clock.callback(500)
        await flush_tasks()

        assert session.engine.rta.clock == 500

    async def test_tick_on_game_over_cancels_and_finalizes(self):
        clock = FakeClock()
        finalize_calls = []

        async def on_finalize(s):
            finalize_calls.append(s)

        session, conn_a, _ = build_session(clock=clock, on_finalize=on_finalize)
        session.start_ticking()
        # Model a king capture: the engine publishes GameEnded (sets _winner)
        # and flips game_active False; _on_tick then sees game over.
        session.engine.events.publish(GameEnded(Color.WHITE))
        session.engine.finish_game()

        clock.callback(50)
        await flush_tasks()

        assert clock.handle.cancelled is True
        assert session._finalized is True
        assert finalize_calls == [session]
        # a GAME_OVER envelope reached the players
        assert any(e.type == MessageType.GAME_OVER for e in conn_a.sent)


class TestFinalize:
    async def test_game_over_payload_has_winner_and_rating_changes(self):
        ratings = GameResultRatings(
            white_old=1200, white_new=1216, black_old=1200, black_new=1184
        )
        persistence = FakePersistence(ratings)
        on_finalize_calls = []

        async def on_finalize(s):
            on_finalize_calls.append(s)

        session, conn_a, conn_b = build_session(
            persistence=persistence, on_finalize=on_finalize
        )
        obs_conn = FakeConnection()
        session.add_observer(PlayerSession("obs", obs_conn))

        # simulate king capture concluding the game
        session._on_game_ended(GameEnded(Color.WHITE))
        await session._finalize(GAME_OVER_REASON_KING_CAPTURED)

        for conn in (conn_a, conn_b, obs_conn):
            envelope = conn.sent[-1]
            assert envelope.type == MessageType.GAME_OVER
            assert envelope.payload["winner"] == Color.WHITE.value
            assert envelope.payload["reason"] == GAME_OVER_REASON_KING_CAPTURED
            changes = envelope.payload["rating_changes"]
            assert len(changes) == 2
            by_user = {c["username"]: c for c in changes}
            assert by_user["white"]["old_rating"] == 1200
            assert by_user["white"]["new_rating"] == 1216
            assert by_user["black"]["new_rating"] == 1184
        assert on_finalize_calls == [session]

    async def test_elo_failure_still_sends_game_over_with_no_rating_changes(self):
        session, conn_a, conn_b = build_session(persistence=FailingPersistence())

        session._on_game_ended(GameEnded(Color.WHITE))
        await session._finalize(GAME_OVER_REASON_KING_CAPTURED)

        assert session._finalized is True
        for conn in (conn_a, conn_b):
            envelope = conn.sent[-1]
            assert envelope.type == MessageType.GAME_OVER
            assert envelope.payload["winner"] == Color.WHITE.value
            assert envelope.payload["rating_changes"] == []

    async def test_finalize_is_idempotent(self):
        session, conn_a, _ = build_session()
        session._on_game_ended(GameEnded(Color.WHITE))
        await session._finalize(GAME_OVER_REASON_KING_CAPTURED)
        sent_after_first = len(conn_a.sent)
        await session._finalize(GAME_OVER_REASON_KING_CAPTURED)
        assert len(conn_a.sent) == sent_after_first

    async def test_one_dead_recipient_does_not_swallow_game_over(self):
        """§8.11: the GAME_OVER send loop must isolate a failing recipient
        the same way every other fan-out does -- a disconnected observer must
        not prevent the players from being told the game ended."""
        conn_a, conn_b = FakeConnection(), FakeConnection()
        player_a = PlayerSession("white", conn_a)
        player_b = PlayerSession("black", conn_b)
        session = GameSession(
            player_a, player_b, FakeClock(), FakePersistence(), room_id="room1",
        )
        session.add_observer(PlayerSession("obs", FailingConnection()))

        session._on_game_ended(GameEnded(Color.WHITE))
        await session._finalize(GAME_OVER_REASON_KING_CAPTURED)

        for conn in (conn_a, conn_b):
            assert conn.sent[-1].type == MessageType.GAME_OVER


class TestFinalizeByForfeit:
    async def test_forfeit_cancels_submits_and_broadcasts(self):
        clock = FakeClock()
        persistence = FakePersistence()
        session, conn_a, conn_b = build_session(clock=clock, persistence=persistence)
        session.start_ticking()

        await session.finalize_by_forfeit(Color.BLACK, GAME_OVER_REASON_DISCONNECT)

        assert clock.handle.cancelled is True
        assert len(persistence.submissions) == 1
        assert not session.engine.game_active
        over = conn_a.sent[-1]
        assert over.type == MessageType.GAME_OVER
        assert over.payload["winner"] == Color.BLACK.value
        assert over.payload["reason"] == GAME_OVER_REASON_DISCONNECT

    async def test_forfeit_is_idempotent(self):
        persistence = FakePersistence()
        session, conn_a, _ = build_session(persistence=persistence)

        await session.finalize_by_forfeit(Color.BLACK, GAME_OVER_REASON_DISCONNECT)
        sent_after_first = len(conn_a.sent)
        await session.finalize_by_forfeit(Color.BLACK, GAME_OVER_REASON_DISCONNECT)

        assert len(persistence.submissions) == 1
        assert len(conn_a.sent) == sent_after_first


class TestGameRegistry:
    def test_create_game_stores_maps_and_starts_ticking(self):
        registry = GameRegistry()
        clock = FakeClock()
        persistence = FakePersistence()
        player_a = PlayerSession("white", FakeConnection())
        player_b = PlayerSession("black", FakeConnection())

        game = registry.create_game(
            player_a, player_b, clock, persistence, room_id="r1"
        )

        assert registry.get(game.id) is game
        assert registry.get_game_for_player("white") is game
        assert registry.get_game_for_player("black") is game
        assert clock.callback is not None  # start_ticking wired the clock

    def test_remove_cancels_handle_and_clears_mappings(self):
        registry = GameRegistry()
        clock = FakeClock()
        player_a = PlayerSession("white", FakeConnection())
        player_b = PlayerSession("black", FakeConnection())
        game = registry.create_game(
            player_a, player_b, clock, FakePersistence(), room_id="r1"
        )

        registry.remove(game.id)

        assert registry.get(game.id) is None
        assert registry.get_game_for_player("white") is None
        assert clock.handle.cancelled is True

    def test_add_observer_resolves_via_get_game_for_player(self):
        registry = GameRegistry()
        player_a = PlayerSession("white", FakeConnection())
        player_b = PlayerSession("black", FakeConnection())
        game = registry.create_game(
            player_a, player_b, FakeClock(), FakePersistence(), room_id="r1"
        )

        registry.add_observer(game.id, "obs")

        assert registry.get_game_for_player("obs") is game

    def test_remove_player_mapping_drops_a_single_entry(self):
        registry = GameRegistry()
        player_a = PlayerSession("white", FakeConnection())
        player_b = PlayerSession("black", FakeConnection())
        game = registry.create_game(
            player_a, player_b, FakeClock(), FakePersistence(), room_id="r1"
        )
        registry.add_observer(game.id, "obs")

        registry.remove_player_mapping("obs")

        assert registry.get_game_for_player("obs") is None
        assert registry.get_game_for_player("white") is game  # unaffected

    def test_remove_clears_observer_mappings_too(self):
        registry = GameRegistry()
        player_a = PlayerSession("white", FakeConnection())
        player_b = PlayerSession("black", FakeConnection())
        game = registry.create_game(
            player_a, player_b, FakeClock(), FakePersistence(), room_id="r1"
        )
        registry.add_observer(game.id, "obs")
        game.add_observer(PlayerSession("obs", FakeConnection()))

        registry.remove(game.id)

        assert registry.get_game_for_player("obs") is None
