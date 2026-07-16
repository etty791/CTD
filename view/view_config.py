from model.piece import State

DEFAULT_BOARD_SIZE=8
SQUARE_SIZE=1

STATE_ASSET_FOLDER = {
    State.idle: "idle",
    State.moving: "move",
    State.airborne: "jump",
}
MS_PER_SECOND = 1000
FRAME_DELAY_MS = 33
WAIT_TICK_INTERVAL_SECONDS = 1.0
