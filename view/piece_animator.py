import time
from view.view_config import STATE_ASSET_FOLDER


class PieceAnimator:
    """Tracks, per piece id, which state a piece is animating and how long
    it has been in that state, so GameRenderer can pick the right sprite
    frame across successive render_frame calls even though each call only
    receives a stateless snapshot."""

    def __init__(self, asset_manager):
        self._assets = asset_manager
        self._entries = {}

    def frame_for(self, piece_dto, asset_name):
        state_folder = STATE_ASSET_FOLDER[piece_dto.state]
        piece_state = self._assets.get_piece_state(asset_name, state_folder)
        sprites = piece_state["sprites"]
        graphics = piece_state["config"]["graphics"]

        entry = self._entries.get(piece_dto.id)
        now = time.time()
        if entry is None or entry["state_folder"] != state_folder:
            entry = {"state_folder": state_folder, "entered_at": now}
            self._entries[piece_dto.id] = entry

        elapsed_seconds = now - entry["entered_at"]
        frame_index = int(elapsed_seconds * graphics["frames_per_sec"])
        if graphics["is_loop"]:
            frame_index %= len(sprites)
        else:
            frame_index = min(frame_index, len(sprites) - 1)

        return sprites[frame_index]

    def prune(self, live_piece_ids):
        """Drop tracked animation state for pieces no longer in the
        snapshot (e.g. captured), so the entry map doesn't grow unbounded."""
        stale_ids = [piece_id for piece_id in self._entries if piece_id not in live_piece_ids]
        for piece_id in stale_ids:
            del self._entries[piece_id]
