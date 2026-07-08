from rules import * 
from constants import * 

class KungFuChessGame:
    def __init__(self, initial_board,movement_rules=None):
        self.board = initial_board
        self.clock=0
        self.selected_piece_coords = None
        self.movement_rules = movement_rules or DEFAULT_MOVEMENT_RULES
        self.pending_moves = []
        self.game_active = True

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
        to_move_color = self.get_piece_color(to_move)
    
        for move in self.pending_moves:
            if move['origin'] == origin:
                return False
            # Only one color may have pending moves at a time
            # if self.get_piece_color(move['piece']) != to_move_color:
            #     return False

        from_row, from_col = origin
        to_row, to_col = target
        
        # row_step = 0 if to_row == from_row else (1 if to_row > from_row else -1)
        # col_step = 0 if to_col == from_col else (1 if to_col > from_col else -1)
        
        # curr_row = from_row 
        # curr_col = from_col

        # while curr_row != to_row or curr_col != to_col:
        #     self.board.set_piece_at((curr_row, curr_col), EMPTY_CELL)
        #     self.handle_wait(DEFAULT_MOVE_DELAY_MS)
        #     curr_row += row_step
        #     curr_col += col_step
        #     if not self.board.is_cell_empty((curr_row, curr_col)):
        #         self.board.set_piece_at((from_row, from_col), to_move)
        #         return False
        #     self.board.set_piece_at((curr_row, curr_col), to_move)
             
        row_diff = abs(to_row - from_row)
        col_diff = abs(to_col - from_col)
        distance = max(row_diff, col_diff)
        
        # Determine when the move should arrive based on distance
        arrival_time = self.clock + (distance * DEFAULT_MOVE_DELAY_MS)
        
        # Add to pending moves instead of blocking execution
        self.pending_moves.append({
            'piece': to_move,
            'origin': origin,
            'target': target,
            'arrival_time': arrival_time
        })
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
        if not self.game_active:
            return
        col = self.transfer_pixels_to_data(x)
        row = self.transfer_pixels_to_data(y)

        if not self.board.is_within_boundaries((row,col)):
            return 
        clicked_piece = self.board.get_piece_at((row,col))
    
        if not self.selected_piece_coords:
            if not self.board.is_cell_empty((row,col)):
                self.selected_piece_coords = (row, col)
            return
        
        sel_row, sel_col = self.selected_piece_coords
        selected_piece = self.board.get_piece_at((sel_row, sel_col))

        if self.get_piece_color(clicked_piece) == self.get_piece_color(selected_piece):
            self.selected_piece_coords = (row, col)
        elif self.move(selected_piece,(sel_row,sel_col),(row,col)):
            self.selected_piece_coords = None
            
            
    def handle_wait(self, ms):
        self.clock += ms
        arrived_moves = [m for m in self.pending_moves if m['arrival_time'] <= self.clock]
        
        arrived_moves.sort(key=lambda m: m['arrival_time'])
        
        target_groups = {}
        for move in arrived_moves:
            if move['target'] not in target_groups:
                target_groups[move['target']] = []
            target_groups[move['target']].append(move)

        for target, moves in target_groups.items():
            # Enemy collisions
            if len(moves) > 1:
                for m in moves:
                    if self.board.get_piece_at(m['origin']) == m['piece']:
                        self.board.set_piece_at(m['origin'], EMPTY_CELL)
                    self.pending_moves.remove(m)
                
                self.board.set_piece_at(target, EMPTY_CELL)
                continue 

            move = moves[0]
            
            # Movement conflicts
            if self.board.get_piece_at(move['origin']) != move['piece']:
                self.pending_moves.remove(move)
                continue

            piece_type = self.get_piece_type(move['piece'])

            sliders =  NON_JUMPERS
            if piece_type in sliders:
                if not self.is_path_clear(move['origin'], move['target']):
                    self.pending_moves.remove(move)
                    continue

            # Friendly-piece landing
            target_piece = self.board.get_piece_at(move['target'])
            if target_piece != EMPTY_CELL:
                if self.get_piece_color(target_piece) == self.get_piece_color(move['piece']):
                    self.pending_moves.remove(move)
                    continue
            
            self.board.set_piece_at(move['origin'], EMPTY_CELL)
            if self.board.get_piece_at(move['target']) == KING:
                self.finish_game(self.get_piece_color(move['piece']))
            self.board.set_piece_at(move['target'], move['piece'])
            self.pending_moves.remove(move)
    def finish_game(self, winner_color):
        self.game_active = False