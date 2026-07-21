# view/renderer.py
import numpy as np

from view.view_config import *
from view.img import Img
from view.piece_animator import PieceAnimator
from model.piece import Color

class GameRenderer:
    def __init__(self, asset_manager, scene_animator=None):
        self._assets = asset_manager
        self._animator = PieceAnimator(asset_manager)
        self._scene_animator = scene_animator
        board_height, board_width = asset_manager.get_board().img.shape[:2]
        self._tile_width = board_width // DEFAULT_BOARD_SIZE
        self._tile_height = board_height // DEFAULT_BOARD_SIZE
        self._board_width = board_width
        self._board_height = board_height
        self.score_panel_width = int(board_width * SCORE_SIDE_PANEL_WIDTH_RATIO)
        self._score_font_size = self._tile_height * SCORE_FONT_SIZE_RATIO

    def render_frame(self, game_snapshot) -> Img:
        """
        Creates a single frame based on the current game state.
        game_state is assumed to be an object/dict provided by your game_engine.
        """
        canvas_width = self.score_panel_width + self._board_width + self.score_panel_width
        canvas = Img()
        canvas.img = np.full((self._board_height, canvas_width, 4),
                              SCORE_PANEL_BACKGROUND_COLOR, dtype=np.uint8)

        board_img = self._assets.get_board()
        board_img.draw_on(canvas, self.score_panel_width, 0)

        # 2. Draw pieces
        self._draw_pieces(canvas, game_snapshot)

        # 3. Draw score HUD
        self._draw_score(canvas, game_snapshot)

        # 4. Draw a scene overlay (intro/victory) on top, if one is active.
        self._draw_scene(canvas)

        return canvas

    def _draw_scene(self, canvas: Img) -> None:
        if self._scene_animator is None or not self._scene_animator.is_active():
            return
        scene_frame = self._scene_animator.current_frame()
        if scene_frame is not None:
            scene_frame.draw_on(canvas, 0, 0)

    def _draw_pieces(self, canvas: Img, game_state) -> None:
        """Iterates over active pieces and draws them on the canvas."""
        pieces = game_state.get_all_pieces()
        self._animator.prune({piece.id for piece in pieces})

        for piece in pieces:
            asset_name = f"{piece.color.value}{piece.type.value}"
            sprite = self._animator.frame_for(piece, asset_name)

            x, y = self._pixel_position(piece)
            sprite.draw_on(canvas, x, y)

    def _draw_score(self, canvas: Img, game_snapshot) -> None:
        """Draws each color's running score in its own side panel outside
        the board - White to the left, Black to the right - so the HUD
        never overlaps the board's squares or pieces."""
        scores = game_snapshot.get_scores()

        white_text = f"White: {scores[Color.WHITE]}"
        canvas.put_text(white_text, SCORE_TEXT_MARGIN_PX, SCORE_TEXT_Y_PX,
                         self._score_font_size, SCORE_TEXT_COLOR, SCORE_TEXT_THICKNESS)

        black_text = f"Black: {scores[Color.BLACK]}"
        black_x = self.score_panel_width + self._board_width + SCORE_TEXT_MARGIN_PX
        canvas.put_text(black_text, black_x, SCORE_TEXT_Y_PX,
                         self._score_font_size, SCORE_TEXT_COLOR, SCORE_TEXT_THICKNESS)

    def _pixel_position(self, piece) -> tuple[int, int]:
        """Lerps a piece's pixel position between its move/jump origin and
        target by its progress (0.0-1.0); idle pieces have origin==target
        so this reduces to their fixed cell. Offset by the left score panel
        width since the board is drawn starting there, not at x=0."""
        origin_x = self.score_panel_width + piece.origin.y * self._tile_width
        origin_y = piece.origin.x * self._tile_height
        target_x = self.score_panel_width + piece.target.y * self._tile_width
        target_y = piece.target.x * self._tile_height

        x = origin_x + (target_x - origin_x) * piece.progress
        y = origin_y + (target_y - origin_y) * piece.progress
        return int(x), int(y)
