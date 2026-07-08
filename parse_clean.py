import sys



def is_valid_board(board,valid):
    if not board:
        print("ERROR UNKNOWN_TOKEN")
        return False
        
    rows = len(board)
    cols = len(board[0])
    
    if cols == 0:
        return False

    for row in board:
        if len(row) != cols:
            print("ERROR ROW_WIDTH_MISMATCH")
            return False
            
        for cell in row:
            if cell not in valid:
                print("ERROR UNKNOWN_TOKEN")
                return False
                
    return True

def parse_input():
    lines = sys.stdin.read().splitlines()

    parsing_board = False
    parsing_commands = False
    board = []
    commands=[]

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

        if clean_line == "Board:":
            parsing_board = True
            parsing_commands = False
            continue
        elif clean_line == "Commands:":
            parsing_board = False
            parsing_commands = True
            continue

        if parsing_board:
            board.append(clean_line.split())
        
        elif parsing_commands:
            commands.append(clean_line)
    
    if not is_valid_board(board):
        exit(1)
        
    if not commands:
        print("ERROR UNKNOWN_TOKEN")

    return board,commands