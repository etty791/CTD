def compute_diff(origin,target):
    from_row, from_col = origin
    to_row, to_col = target
    row_diff = abs(to_row - from_row)
    col_diff = abs(to_col - from_col)
    return row_diff,col_diff

def validate_king_move(origin, target, color, game):
    row_diff,col_diff=compute_diff(origin,target)
    return row_diff <= 1 and col_diff<= 1

def validate_rook_move(origin, target, color, game):
    row_diff,col_diff=compute_diff(origin,target)
    if row_diff== 0 or col_diff == 0:
        return game.is_path_clear(origin, target)
    return False

def validate_bishop_move(origin, target, color, game):
    row_diff,col_diff=compute_diff(origin,target)

    if row_diff==col_diff:
        return game.is_path_clear(origin, target)
    return False

def validate_queen_move(origin, target, color, game):
    if validate_bishop_move(origin,target,color,game) and validate_rook_move(origin, target, color, game):
        return game.is_path_clear(origin, target)
    return False

def validate_knight_move(origin, target, color, game):
    row_diff,col_diff=compute_diff(origin,target)
    return (row_diff == 2 and col_diff == 1) or (row_diff == 1 and col_diff == 2)

def validate_pawn_move(origin, target, color, game):
    from_row, from_col = origin
    to_row, to_col = target
    col_diff = abs(to_col - from_col)
    
    valid_direction = (color == 'w' and from_row == to_row + 1) or (color == 'b' and from_row == to_row - 1)
    
    if valid_direction:
        if col_diff == 0:
            return game.is_cell_empty(to_row, to_col)
        
        elif col_diff == 1:
            target_piece = game.get_piece_at(to_row, to_col)
            if game.is_cell_empty(to_row, to_col):
                target_color = game.get_piece_color(target_piece)
                return target_color != color
    return False

DEFAULT_MOVEMENT_RULES = {
    'K': validate_king_move,
    'R': validate_rook_move,
    'B': validate_bishop_move,
    'Q': validate_queen_move,
    'N': validate_knight_move,
    'P': validate_pawn_move
}