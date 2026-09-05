import logging
import os

from events.event_bus import EventBus
from events.game_events import GameStarted, GameEnded, MoveStarted, PieceCaptured
from view.view_config import SOUND_ASSET_MAP, SOUND_ASSETS_DIR

logger = logging.getLogger(__name__)

try:
    import winsound
except ImportError:  # pragma: no cover - winsound is Windows-only stdlib
    winsound = None


class SoundPlayer:
    """Plays one sound per subscribed event type. Playback is fire-and-
    forget via winsound's SND_ASYNC flag, so it never blocks advance_time
    or the render loop; a missing sound file or missing winsound support
    logs a warning and is skipped rather than raising."""

    def __init__(self, event_bus: EventBus):
        event_bus.subscribe(MoveStarted, self._on_event)
        event_bus.subscribe(PieceCaptured, self._on_event)
        event_bus.subscribe(GameStarted, self._on_event)
        event_bus.subscribe(GameEnded, self._on_event)

    def _on_event(self, event) -> None:
        filename = SOUND_ASSET_MAP.get(type(event))
        if filename is None:
            return

        path = os.path.join(SOUND_ASSETS_DIR, filename)
        if not os.path.isfile(path):
            logger.warning("Sound asset missing for %s: %s", type(event).__name__, path)
            return

        if winsound is None:
            logger.warning("winsound is unavailable - skipping playback of %s", path)
            return

        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
