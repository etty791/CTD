from shared.protocol_config import DEFAULT_BOARD_SIZE
class BoardMapper:
    def __init__(self,board_width, board_height):
        self.board_width = board_width
        self.board_height=board_height
    def pixels_to_logic(self,x, y):
        """מתרגם קואורדינטות של פיקסלים לאינדקסים של מטריצת הלוח"""
        col = (x * DEFAULT_BOARD_SIZE) // self.board_width
        row = (y * DEFAULT_BOARD_SIZE) // self.board_height
        return row, col

