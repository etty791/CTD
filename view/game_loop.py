import cv2
import time

from view.view_config import *

class GameLoop:
    def __init__(self, game, asset_manager, renderer, controller):
        self.game = game
        self.asset_manager = asset_manager
        self.renderer = renderer
        self.controller = controller

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

            if key == ord('q') or cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                self.running = False

        cv2.destroyAllWindows()