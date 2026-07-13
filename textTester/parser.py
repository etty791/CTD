import sys
from model.piece import Piece
from model.position import Position
from model.board import EMPTY_CELL


def parse_input(valid_tokens):
    lines = sys.stdin.read().splitlines()

    parsing_board = False
    board_lines = []
    command_lines=[]
    if not lines or  lines[0].strip() != "Board:":
        print("ERROR UNKNOWN_TOKEN")
        return None, None
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

        if clean_line == "Board:":
            parsing_board = True
            continue
        elif clean_line == "Commands:":
            parsing_board = False
            continue

        if parsing_board:
            board_lines.append(clean_line.split())
        else:
            command_lines.append(clean_line)
    

    if not command_lines or not board_lines:
        print("ERROR UNKNOWN_TOKEN")
        return None, None

    board = create_board(board_lines,valid_tokens)
    commands = create_commands(command_lines)

    return board, commands


def is_valid_board(board,valid):
    if not board:
        print("ERROR UNKNOWN_TOKEN")
        return False
        
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


def create_piece_from_string(token, x, y, piece_id_counter):
    if token == EMPTY_CELL:
        return EMPTY_CELL
    color = token[0]
    kind = token[1]
    return Piece(id_num=piece_id_counter, color=color, kind=kind, position=Position(x, y))

def create_board(board_lines, valid_tokens):
    if not is_valid_board(board_lines, valid_tokens):
        exit(1)
    board = []
    piece_id_counter = 1
    for x, row in enumerate(board_lines):
        board_row = []
        for y, token in enumerate(row):
            piece = create_piece_from_string(token, x, y, piece_id_counter)
            if piece != EMPTY_CELL:
                piece_id_counter += 1
            board_row.append(piece)
        board.append(board_row)
    return board

def create_commands(command_lines):
    commands = []
    for cmd in command_lines:
        parts = cmd.split()
        action = parts[0]
        if action not in ["click", "wait", "print"]:
            print("ERROR UNKNOWN_TOKEN")
            exit(1)
        
        if action == "click":
            x = int(parts[1])
            y = int(parts[2])
            commands.append(("click", x, y))
        elif action == "wait":
            ms = int(parts[1])
            commands.append(("wait", ms))
        elif action == "print":
            if parts[1] == "board":
                commands.append(("print",))
    return commands
