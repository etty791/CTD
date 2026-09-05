from view.GUI_runner import run_GUI
from game_engine.game import KungFuChessGame

def main():
    game=KungFuChessGame()
    run_GUI(game)

if __name__ == "__main__":
    main()

