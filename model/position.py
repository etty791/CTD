class Position:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __str__(self):
        return f"({self.x}, {self.y})"
    def __eq__(self, value):
        return self.x == value.x and self.y == value.y
    def __hash__(self):
        return hash((self.x, self.y))
    def __add__(self, other: "Position") -> "Position":
        return Position(self.x + other.x, self.y + other.y)
    
