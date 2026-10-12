class ParseError(ValueError):
    """Raised when LaTeX cannot be turned into an expression. `pos` is a character offset."""

    def __init__(self, message: str, pos: int = -1):
        super().__init__(message)
        self.pos = pos
