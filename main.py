VALID_TOKENS = {
    '.',
    'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
    'bK', 'bQ', 'bR', 'bB', 'bN', 'bP'
}
from parse_clean import parse_input 
from game import KungFuChessGame 
from board import Board

def main():
    board, commands = parse_input(VALID_TOKENS)
    game = KungFuChessGame(Board(board))
    
    for cmd in commands:
        parts = cmd.split()
        action = parts[0]
        
        if action == "click":
            x = int(parts[1])
            y = int(parts[2])
            game.handle_click(x, y)
        elif action == "wait":
            ms = int(parts[1])
            game.handle_wait(ms)
        elif action == "print":
            if parts[1] == "board":
                game.board.print_board()
        else:
            print("ERROR UNKNOWN_TOKEN")

if __name__ == "__main__":
    main()