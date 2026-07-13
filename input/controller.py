from input.board_mapper import transfer_pixels_to_data 
from model.position import Position

selected_piece_pos = None
def handle_click(game, x, y):
        global selected_piece_pos
        if not game.game_active:
            return
        col = transfer_pixels_to_data(x)
        row = transfer_pixels_to_data(y)
        pos = Position(row, col)

        if not game.board.is_within_boundaries(pos):
            selected_piece_pos = None
            return

        clicked_piece = game.board.get_piece_at(pos)

        if not selected_piece_pos:
            if not game.board.is_cell_empty(pos):
                selected_piece_pos = pos
            return

        selected_pos = selected_piece_pos
        selected_piece = game.board.get_piece_at(selected_pos)

        if game.board.is_cell_empty(pos):
            game.move_request(selected_pos, pos)
            selected_piece_pos = None
        elif clicked_piece.color != selected_piece.color:
            game.move_request(selected_pos, pos)
            selected_piece_pos = None
        else:
            selected_piece_pos = pos
            