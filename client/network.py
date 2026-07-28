"""ServerConnection: owns the network thread.

Threading model: a background daemon thread runs its own asyncio event loop
and a `websockets` client connection. The REPL and the cv2 GUI both run on
the main thread. Outbound sends are marshalled onto the network loop via
`run_coroutine_threadsafe`; inbound envelopes are routed either straight to
the active RemoteGame (STATE / GAME_OVER, while a game is in progress) or
onto a thread-safe queue the main thread blocks on (`wait_for`), mirroring
the request/response shape of the shell's register/login/room/play flow.
"""

import asyncio
import queue
import threading
import time

import websockets

from client.client_config import RESPONSE_TIMEOUT_S
from shared.messages import EventPayload, GameOverPayload, StatePayload
from shared.protocol import Envelope, MessageType

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
        self._pending_state: StatePayload | None = None  # a STATE that beat set_active_game
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
        # A STATE envelope can arrive before a RemoteGame exists to receive
        # it: the server sends GAME_START then immediately STATE (an observer
        # joining a live game, or the second player's join completing the
        # room) faster than the main thread can process wait_for's GAME_START
        # return and call set_active_game. Rather than synchronizing across
        # the threads, the newest such frame is held here and handed to the
        # game the moment it attaches. It cannot simply be dropped: the
        # server publishes STATE on change, so on a quiet board the next one
        # may be a full heartbeat away and the player would stare at an empty
        # board until someone moved.
        if envelope.type == MessageType.STATE:
            state = StatePayload.model_validate(envelope.payload)
            if self._active_game is None:
                self._pending_state = state
            else:
                self._active_game.apply_state(state)
            return
        if envelope.type == MessageType.GAME_OVER:
            if self._active_game is not None:
                self._active_game.end_game(GameOverPayload.model_validate(envelope.payload))
                return
            # Defensive fallback: shouldn't happen (GAME_OVER always follows
            # an active game), but don't lose it silently if it does.
        if envelope.type == MessageType.EVENT:
            # Transient/cosmetic (a move-started/capture cue) -- unlike
            # STATE, dropping one before a game attaches is harmless, so
            # there's no pending-buffer equivalent. Must return
            # unconditionally: falling through to inbox.put would let a
            # dropped EVENT be misconsumed by an unrelated later wait_for.
            if self._active_game is not None:
                self._active_game.apply_event(EventPayload.model_validate(envelope.payload))
            return
        self.inbox.put(envelope)

    def set_active_game(self, remote_game) -> None:
        """Attach (or, with None, detach) the game inbound STATE frames feed.
        A frame that beat the attachment is replayed here so the board is
        populated from the very first rendered frame."""
        self._active_game = remote_game
        pending, self._pending_state = self._pending_state, None
        if remote_game is not None and pending is not None:
            remote_game.apply_state(pending)

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
