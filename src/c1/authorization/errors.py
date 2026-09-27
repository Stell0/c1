"""Safe security boundary failures without backend response bodies."""


class SecurityError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(reason)
