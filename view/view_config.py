from model.piece import State
from events.game_events import GameStarted, GameEnded, MoveStarted, PieceCaptured

DEFAULT_BOARD_SIZE=8
SQUARE_SIZE=1

STATE_ASSET_FOLDER = {
    State.idle: "idle",
    State.moving: "move",
    State.airborne: "jump",
    State.long_rest: "long_rest",
    State.short_rest: "short_rest",
}
MS_PER_SECOND = 1000
FRAME_DELAY_MS = 33
WAIT_TICK_INTERVAL_SECONDS = 1.0

# Board-level overlay scenes (SceneAnimator) - a distinct concept from
# per-piece STATE_ASSET_FOLDER above: only one of these plays at a time,
# keyed by scene name rather than by piece State, and each folder is
# expected under view/assets/scenes/<folder>/ (config.json + sprites/,
# same shape AssetManager already loads for pieces).
SCENE_ASSET_FOLDER = {
    "intro": "intro",
    "victory": "victory",
}

# SoundPlayer: one sound file per subscribed event type, under
# SOUND_ASSETS_DIR. Files are not bundled yet - SoundPlayer logs a
# warning and skips playback when a mapped file is missing.
SOUND_ASSETS_DIR = "view/assets/sounds"
SOUND_ASSET_MAP = {
    MoveStarted: "move.wav",
    PieceCaptured: "capture.wav",
    GameStarted: "game_start.wav",
    GameEnded: "game_end.wav",
}

SCORE_TEXT_COLOR = (255, 255, 255, 255)
SCORE_TEXT_THICKNESS = 2
SCORE_TEXT_MARGIN_PX = 10
SCORE_TEXT_Y_PX = 40
# The board image has no dedicated UI margin of its own - the checkerboard
# starts at pixel (0, 0) - so each player's score lives in a dedicated
# side panel outside the board itself: White's panel to the left, Black's
# to the right. SCORE_PANEL_BACKGROUND_COLOR fills both panels.
# Panel width and font size are ratios (of board width / tile height,
# respectively) rather than fixed pixel counts, so the HUD stays
# proportional if the board asset's resolution ever changes.
SCORE_SIDE_PANEL_WIDTH_RATIO = 0.2
SCORE_FONT_SIZE_RATIO = 0.007
SCORE_PANEL_BACKGROUND_COLOR = (0, 0, 0, 255)
