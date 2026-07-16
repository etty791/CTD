from view.view_config import *  
class BoardMapper:
    def __init__(self,board_width, board_height):
        self.board_width = board_width
        self.board_height=board_height
    def pixels_to_logic(self,x, y):
        """מתרגם קואורדינטות של פיקסלים לאינדקסים של מטריצת הלוח"""
        col = (x * DEFAULT_BOARD_SIZE) // self.board_width
        row = (y * DEFAULT_BOARD_SIZE) // self.board_height
        return row, col
        
    
    def logic_to_pixels(self,row, col):
        """(אופציונלי) מתרגם אינדקס של מטריצה לנקודת ההתחלה של הפיקסלים - שימושי לציור"""
        x = (col * self.board_width) //DEFAULT_BOARD_SIZE
        y = (row * self.board_height) //DEFAULT_BOARD_SIZE
        return x, y
    




