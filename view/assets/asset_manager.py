import json
from pathlib import Path
from view.img import Img
from view.view_config import DEFAULT_BOARD_SIZE

class AssetManager:
    def __init__(self, base_path="assets"):
        current_file_dir = Path(__file__).resolve().parent

        self.base_path = current_file_dir
        self._assets = {
            "board": None,
            "pieces": {}
        }
        self.load_initial()

    def load_initial(self):
        board = Img()
        import os
        print("Files Python sees in assets:", os.listdir(self.base_path))
        board.read(str(self.base_path / "board.png"))
        self._assets["board"] = board

        board_height, board_width = board.img.shape[:2]
        tile_size = (board_width // DEFAULT_BOARD_SIZE, board_height // DEFAULT_BOARD_SIZE)
        self._load_pieces(tile_size)

    def _load_pieces(self, tile_size):
        pieces_dir = self.base_path / "pieces"

        if not pieces_dir.exists():
            print(f"Directory {pieces_dir} not found!")
            return

        for piece_path in pieces_dir.iterdir():
            if not piece_path.is_dir():
                continue
                
            piece_name = piece_path.name
            self._assets["pieces"][piece_name] = {}

            states_dir = piece_path / "states"
            if not states_dir.exists():
                continue

            for state_path in states_dir.iterdir():
                if not state_path.is_dir():
                    continue
                    
                state_name = state_path.name
                
                state_data = {
                    "config": {},
                    "sprites": []
                }
                
                config_file = state_path / "config.json"
                if config_file.exists():
                    with open(config_file, 'r', encoding='utf-8') as f:
                        state_data["config"] = json.load(f)
                
                sprites_dir = state_path / "sprites"
                if sprites_dir.exists():
                    for sprite_file in sorted(sprites_dir.iterdir()):
                        if sprite_file.suffix.lower() in ['.png', '.jpg']:
                            img = Img()
                            img.read(str(sprite_file), size=tile_size, keep_aspect=True)
                            state_data["sprites"].append(img)
                
                self._assets["pieces"][piece_name][state_name] = state_data

    def get_board(self):
        return self._assets["board"]

    #change to color and piece type?
    def get_piece_state(self, piece_name, state_name):
        """
        מחזיר מילון עם config ורשימת sprites עבור כלי ומצב ספציפיים
        """
        return self._assets["pieces"].get(piece_name, {}).get(state_name, None)
