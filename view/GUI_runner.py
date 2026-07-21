from view.assets.asset_manager import AssetManager
from input.board_mapper import BoardMapper
from view.renderer import GameRenderer
from view.scene_animator import SceneAnimator
from view.sound_player import SoundPlayer
from input.controller import Controller
from view.game_loop import GameLoop
def run_GUI(game_engine):
    asset_manager = AssetManager()

    board_image = asset_manager.get_board()
    height, width, _ = board_image.img.shape
    board_mapper = BoardMapper(width, height)
    controller=Controller(game_engine,board_mapper)
    scene_animator = SceneAnimator(game_engine.events, asset_manager)
    renderer = GameRenderer(asset_manager, scene_animator)
    sound_player = SoundPlayer(game_engine.events)
    game_loop = GameLoop(game_engine, asset_manager, renderer, controller)
    game_loop.run()