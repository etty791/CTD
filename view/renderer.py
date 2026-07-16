# view/renderer.py
from view.view_config import *
from view.img import Img
from view.piece_animator import PieceAnimator

class GameRenderer:
    def __init__(self, asset_manager):
        self._assets = asset_manager
        self._animator = PieceAnimator(asset_manager)
        board_height, board_width = asset_manager.get_board().img.shape[:2]
        self._tile_width = board_width // DEFAULT_BOARD_SIZE
        self._tile_height = board_height // DEFAULT_BOARD_SIZE

    def render_frame(self, game_snapshot) -> Img:
        """
        Creates a single frame based on the current game state.
        game_state is assumed to be an object/dict provided by your game_engine.
        """
        canvas = Img()
        board_img = self._assets.get_board()
        canvas.img = board_img.img.copy()

        # 2. Draw pieces
        self._draw_pieces(canvas, game_snapshot)

        return canvas

    def _draw_pieces(self, canvas: Img, game_state) -> None:
        """Iterates over active pieces and draws them on the canvas."""
        pieces = game_state.get_all_pieces()
        self._animator.prune({piece.id for piece in pieces})

        for piece in pieces:
            asset_name = f"{piece.color.value}{piece.type.value}"
            sprite = self._animator.frame_for(piece, asset_name)

            x, y = self._pixel_position(piece)
            sprite.draw_on(canvas, x, y)

    def _pixel_position(self, piece) -> tuple[int, int]:
        """Lerps a piece's pixel position between its move/jump origin and
        target by its progress (0.0-1.0); idle pieces have origin==target
        so this reduces to their fixed cell."""
        origin_x = piece.origin.y * self._tile_width
        origin_y = piece.origin.x * self._tile_height
        target_x = piece.target.y * self._tile_width
        target_y = piece.target.x * self._tile_height

        x = origin_x + (target_x - origin_x) * piece.progress
        y = origin_y + (target_y - origin_y) * piece.progress
        return int(x), int(y)