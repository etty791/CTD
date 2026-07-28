import cv2
import time

from view.view_config import *

class GameLoop:
    def __init__(self, game, asset_manager, renderer, controller, scene_animator):
        self.game = game
        self.asset_manager = asset_manager
        self.renderer = renderer
        self.controller = controller
        self.scene_animator = scene_animator

        self.window_name = "Game Window"
        self.running = True

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

        cv2.setMouseCallback(self.window_name, self._mouse_callback)

        self.last_wait_time = time.time()

    def _mouse_callback(self, event, x, y, flags, param):
        # The board is drawn offset within the window by the left score
        # panel's width (see GameRenderer._pixel_position) - translate back
        # to board-local pixels before handing off to the controller.
        board_x = x - self.renderer.score_panel_width

        if event == cv2.EVENT_LBUTTONDOWN:
            self.controller.handle_click(board_x, y)

        elif event == cv2.EVENT_RBUTTONDOWN:
            self.controller.handle_jump(board_x, y)

    def run(self):
        while self.running:
            current_time = time.time()
            elapsed_ms = int((current_time - self.last_wait_time) * MS_PER_SECOND)

            if elapsed_ms > 0:
                self.controller.handle_wait(elapsed_ms)
                self.last_wait_time = current_time

            snapshot = self.game.get_snapshot()
            frame = self.renderer.render_frame(snapshot)

            if frame is not None:
                frame.show(self.window_name)

            key = cv2.waitKey(FRAME_DELAY_MS) & 0xFF
            window_visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) >= 1

            if key == KEY_RESIGN and self.game.game_active:
                self._handle_resign()

            if self._should_exit(key, window_visible):
                self.running = False

        cv2.destroyAllWindows()

    def _handle_resign(self) -> None:
        # Local KungFuChessGame has no server to concede to, so it exposes
        # no resign() -- only RemoteGame does, and this is a silent no-op
        # for local play.
        resign = getattr(self.game, "resign", None)
        if resign is not None:
            resign()

    def _should_exit(self, key, window_visible: bool) -> bool:
        if key == KEY_QUIT or not window_visible:
            return True
        return not self.game.game_active and not self.scene_animator.is_active()