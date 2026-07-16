from view.assets.asset_manager import AssetManager
from input.board_mapper import BoardMapper
from view.renderer import GameRenderer
from input.controller import Controller
from view.game_loop import GameLoop
def run_GUI(game_engine):
    asset_manager = AssetManager()
    
    board_image = asset_manager.get_board()
    height, width, _ = board_image.img.shape
    board_mapper = BoardMapper(width, height)
    controller=Controller(game_engine,board_mapper)
    renderer = GameRenderer(asset_manager)
    game_loop = GameLoop(game_engine, asset_manager, renderer, controller)
    game_loop.run()