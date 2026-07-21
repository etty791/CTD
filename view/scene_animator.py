import time

from events.event_bus import EventBus
from events.game_events import GameStarted, GameEnded
from view.view_config import SCENE_ASSET_FOLDER

NO_SCENE = "none"


class SceneAnimator:
    """Board-level overlay animator for the intro/victory scenes - a
    separate concept from PieceAnimator: it steps frames by elapsed time
    the same way, but is keyed on a single scene state rather than a
    per-piece id, since only one overlay plays at a time."""

    def __init__(self, event_bus: EventBus, asset_manager):
        self._assets = asset_manager
        self._scene = NO_SCENE
        self._entered_at = time.time()
        event_bus.subscribe(GameStarted, self._on_game_started)
        event_bus.subscribe(GameEnded, self._on_game_ended)

    def is_active(self) -> bool:
        return self._scene != NO_SCENE

    def current_frame(self):
        """Returns the Img to draw for the active scene, or None if no
        scene is active or its assets haven't been dropped in yet. A
        non-looping scene dismisses itself back to NO_SCENE once its
        frames are exhausted, so the live board becomes visible again."""
        if self._scene == NO_SCENE:
            return None

        folder = SCENE_ASSET_FOLDER[self._scene]
        scene_asset = self._assets.get_scene(folder)
        if scene_asset is None or not scene_asset["sprites"]:
            return None

        sprites = scene_asset["sprites"]
        graphics = scene_asset["config"].get("graphics", {})
        frames_per_sec = graphics.get("frames_per_sec", 1)
        is_loop = graphics.get("is_loop", False)

        elapsed_seconds = time.time() - self._entered_at
        frame_index = int(elapsed_seconds * frames_per_sec)

        if is_loop:
            frame_index %= len(sprites)
        elif frame_index >= len(sprites):
            self._scene = NO_SCENE
            return None

        return sprites[frame_index]

    def _on_game_started(self, event: GameStarted) -> None:
        self._enter_scene("intro")

    def _on_game_ended(self, event: GameEnded) -> None:
        self._enter_scene("victory")

    def _enter_scene(self, scene: str) -> None:
        self._scene = scene
        self._entered_at = time.time()
