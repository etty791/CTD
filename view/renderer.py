# view/renderer.py
from view.view_config import *
from view.img import Img

class GameRenderer:
    def __init__(self, asset_manager):
        self._assets = asset_manager
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
        #change to maybe map the colors and names 
        for piece in game_state.get_all_pieces():
            asset_name = f"{piece.color.value}{piece.type.value}"
            state_folder = STATE_ASSET_FOLDER[piece.state]
            piece_state = self._assets.get_piece_state(asset_name, state_folder)
            sprite = piece_state["sprites"][0]

            # use a mapper instead
            x = piece.position.y * self._tile_width
            y = piece.position.x * self._tile_height

            sprite.draw_on(canvas, x, y)