from rules import * 
from constants import * 

class KungFuChessGame:
    def __init__(self, initial_board,movement_rules=None):
        self.board = initial_board
        self.clock=0
        self.selected_piece_coords = None
        self.movement_rules = movement_rules or DEFAULT_MOVEMENT_RULES


    def get_piece_color(self, piece):
        return piece[0] if piece != EMPTY_CELL else None

    def get_piece_type(self, piece):
        return piece[1] if piece != EMPTY_CELL else None

    def transfer_pixels_to_data(self,pixels):
        return pixels//PIXELS_PER_CELL

    def is_path_clear(self, origin, target):
        from_row, from_col = origin
        to_row, to_col = target
        
        row_step = 0 if to_row == from_row else (1 if to_row > from_row else -1)
        col_step = 0 if to_col == from_col else (1 if to_col > from_col else -1)
        
        curr_row = from_row + row_step
        curr_col = from_col + col_step
        
        while curr_row != to_row or curr_col != to_col:
            if not self.board.is_cell_empty((curr_row, curr_col)):
                return False
            curr_row += row_step
            curr_col += col_step
            
        return True
    
    def try_move(self, to_move, origin, target):
        from_row, from_col = origin
        to_row, to_col = target
        
        row_step = 0 if to_row == from_row else (1 if to_row > from_row else -1)
        col_step = 0 if to_col == from_col else (1 if to_col > from_col else -1)
        
        curr_row = from_row 
        curr_col = from_col

        while curr_row != to_row or curr_col != to_col:
            self.board.set_piece_at((curr_row, curr_col), EMPTY_CELL)
            self.handle_wait(DEFAULT_MOVE_DELAY_MS)
            curr_row += row_step
            curr_col += col_step
            if not self.board.is_cell_empty((curr_row, curr_col)):
                self.board.set_piece_at((from_row, from_col), to_move)
                return False
            self.board.set_piece_at((curr_row, curr_col), to_move)
             
        return True

    def move(self, to_move, origin, target):
        if origin == target:
            return False
            
        color = self.get_piece_color(to_move)
        piece_type = self.get_piece_type(to_move)
        
        if piece_type in self.movement_rules:
            if self.movement_rules[piece_type](origin, target, color, self):
                return self.try_move(to_move, origin, target)
            
        return False
    

    def handle_click(self, x, y):
        row = self.transfer_pixels_to_data(x)
        col = self.transfer_pixels_to_data(y)

        if not self.is_within_board_boundries((row,col)):
            return 
        clicked_piece = self.board.get_piece_at((row,col))
    
        if not self.selected_piece_coords:
            if self.board.is_cell_empty((row,col)):
                self.selected_piece_coords = (row, col)
            return
        
        sel_row, sel_col = self.selected_piece_coords
        selected_piece = self.board.get_piece_at((sel_row, sel_col))

        if self.get_piece_color(clicked_piece) == self.get_piece_color(selected_piece):
            self.selected_piece_coords = (row, col)
        elif self.move(selected_piece,(sel_row,sel_col),(row,col)):
            self.selected_piece_coords = None
            
            
    def handle_wait(self, ms):
        self.clock+=ms

