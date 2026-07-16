from textTester.script_runner import run_script
from view.renderer  import GameRenderer
from view.GUI_runner import run_GUI
from game_engine.game import KungFuChessGame

def main():
    game=KungFuChessGame()
    run_GUI(game)
    # run_script()

if __name__ == "__main__":
    main()

