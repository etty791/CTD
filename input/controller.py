from input.board_mapper import transfer_pixels_to_data 
from model.position import Position

class Controller:
    def __init__(self, game):
        self.game = game
        self.selected_piece_pos = None
        self.pos = None
    def update_position(self, x, y):
        self.pos = Position(transfer_pixels_to_data(y),transfer_pixels_to_data(x))

    def handle_click(self,x, y):
        if not self.game.game_active:
            return
        self.update_position(x, y)

        if not self.game.board.is_within_boundaries(self.pos):
            self.selected_piece_pos = None
            return

        clicked_piece = self.game.board.get_piece_at(self.pos)

        if not self.selected_piece_pos:
            if not self.game.board.is_cell_empty(self.pos):
                self.selected_piece_pos = self.pos
            return

        selected_piece = self.game.board.get_piece_at(self.selected_piece_pos)

        if self.game.board.is_cell_empty(self.pos) or (clicked_piece.color != selected_piece.color):
            self.game.move_request(self.selected_piece_pos, self.pos)
            self.selected_piece_pos = None
        else:
            self.selected_piece_pos = self.pos

    def handle_jump(self,x, y):
        if not self.game.game_active:
            return
        self.update_position(x, y)
        if not self.game.board.is_within_boundaries(self.pos) or self.game.board.is_cell_empty(self.pos):
            return
        
        self.game.jump_request(self.pos)



