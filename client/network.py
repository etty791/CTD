"""ServerConnection: owns the network thread.

Threading model: a background daemon thread runs its own asyncio event loop
and a `websockets` client connection. The REPL and the cv2 GUI both run on
the main thread. Outbound sends are marshalled onto the network loop via
`run_coroutine_threadsafe`; inbound envelopes are routed either straight to
the active RemoteGame (KEYFRAME / DELTA / GAME_OVER, while a game is in
progress) or onto a thread-safe queue the main thread blocks on (`wait_for`),
mirroring the request/response shape of the shell's register/login/room/play
flow.

Frame sequencing lives here rather than in RemoteGame, because it is a
property of the connection, not of the game: DELTA frames must be applied in
an unbroken run, and a gap in `Envelope.seq` means one was lost. The answer to
a gap is always the same as the answer to every other kind of desync - ask for
a KEYFRAME (RESYNC) and ignore deltas until it lands. That, and not a
heartbeat, is what makes a dropped frame self-healing.
"""

import asyncio
import queue
import threading
import time

import websockets

from client.client_config import RESPONSE_TIMEOUT_S
from shared.messages import DeltaPayload, GameOverPayload, KeyframePayload
from shared.protocol import Envelope, MessageType

# No frame has been seen yet, so the first keyframe of any seq is welcome and
# no delta can be "the next one".
NO_SEQ = -1

# wait_for polls the inbox in bounded slices rather than a single indefinite
# queue.get(). On CPython a C-level blocking wait with no timeout does not
# check for pending signals until it returns, so a truly-unbounded get()
# would make Ctrl+C (KeyboardInterrupt) appear to hang during an indefinite
# wait (timeout=None, used while waiting for a second player to join a
# room). A short timed wait, repeated in a loop, returns control to the
# interpreter often enough for a pending signal to be delivered.
_POLL_INTERVAL_S = 0.5


class ServerConnection:
    def __init__(self, url: str):
        self._url = url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._thread: threading.Thread | None = None
        self.inbox: "queue.Queue[Envelope]" = queue.Queue()
        self._active_game = None  # set by the shell right before/after a GUI session
        # Frames that beat set_active_game, kept in order (see _route).
        self._pending_frames: list[Envelope] = []
        self._last_seq = NO_SEQ
        self._awaiting_keyframe = False
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=RESPONSE_TIMEOUT_S)  # block until connected

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_and_receive())

    async def _connect_and_receive(self) -> None:
        async with websockets.connect(self._url) as ws:
            self._ws = ws
            self._ready.set()
            async for raw in ws:
                envelope = Envelope.model_validate_json(raw)
                self._route(envelope)

    def _route(self, envelope: Envelope) -> None:
        # A state frame can arrive before a RemoteGame exists to receive it:
        # the server sends GAME_START then immediately a KEYFRAME (an observer
        # joining a live game, or the second player's join completing the
        # room) faster than the main thread can process wait_for's GAME_START
        # return and call set_active_game. Rather than synchronizing across
        # the threads, such frames are held here in order and replayed the
        # moment a game attaches. They cannot simply be dropped: the server
        # sends frames only on change, so on a quiet board the player would
        # stare at an empty one until somebody moved.
        if envelope.type in (MessageType.KEYFRAME, MessageType.DELTA):
            if self._active_game is None:
                self._pending_frames.append(envelope)
            else:
                self._apply_frame(envelope)
            return
        if envelope.type == MessageType.GAME_OVER:
            if self._active_game is not None:
                self._active_game.end_game(GameOverPayload.model_validate(envelope.payload))
                return
            # Defensive fallback: shouldn't happen (GAME_OVER always follows
            # an active game), but don't lose it silently if it does.
        self.inbox.put(envelope)

    def _apply_frame(self, envelope: Envelope) -> None:
        if envelope.type == MessageType.KEYFRAME:
            # A personal keyframe (observer join, RESYNC answer) can be
            # overtaken by a broadcast delta, in which case it describes an
            # older game than the one already on screen: applying it would
            # rewind the board.
            if envelope.seq < self._last_seq:
                return
            self._last_seq = envelope.seq
            self._awaiting_keyframe = False
            self._active_game.apply_keyframe(KeyframePayload.model_validate(envelope.payload))
            return

        if self._awaiting_keyframe or envelope.seq <= self._last_seq:
            return  # already superseded, or unusable until the keyframe lands
        if envelope.seq != self._last_seq + 1:
            self._request_resync()
            return
        self._last_seq = envelope.seq
        self._active_game.apply_delta(DeltaPayload.model_validate(envelope.payload))

    def _request_resync(self) -> None:
        """Ask for a keyframe and ignore deltas until it arrives - applying
        them over a board with a hole in it would only compound the desync."""
        self._awaiting_keyframe = True
        self.send(Envelope(type=MessageType.RESYNC))

    def set_active_game(self, remote_game) -> None:
        """Attach (or, with None, detach) the game inbound frames feed. Frames
        that beat the attachment are replayed here in order, so the board is
        populated and in sequence from the very first rendered frame."""
        self._active_game = remote_game
        pending, self._pending_frames = self._pending_frames, []
        if remote_game is None:
            self._last_seq = NO_SEQ
            self._awaiting_keyframe = False
            return
        for envelope in pending:
            self._apply_frame(envelope)

    def send(self, envelope: Envelope) -> None:
        asyncio.run_coroutine_threadsafe(self._ws.send(envelope.model_dump_json()), self._loop)

    def wait_for(self, expected_types: set, timeout: float | None) -> Envelope:
        """Block until an envelope whose type is in expected_types (or ERROR)
        arrives on the inbox. timeout=None blocks indefinitely (used while
        waiting in a created room for a second player, matching there being
        no server-side timeout for that case -- only `play` has one) but
        stays Ctrl+C-interruptible by polling in bounded slices -- see
        _POLL_INTERVAL_S."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no response within {timeout}s")
                poll = min(_POLL_INTERVAL_S, remaining)
            else:
                poll = _POLL_INTERVAL_S
            try:
                envelope = self.inbox.get(timeout=poll)
            except queue.Empty:
                continue
            if envelope.type in expected_types or envelope.type == MessageType.ERROR:
                return envelope
            # Not what we're waiting for -- discard and keep waiting. Shouldn't
            # normally happen given the strict request/response shell flow.

    def close(self) -> None:
        if self._ws is not None and self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
