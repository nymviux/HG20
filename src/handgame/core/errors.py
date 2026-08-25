class HandGameException(Exception):
    """Bazowa klasa wyjątków dla aplikacji HandGame."""
    pass

class InvalidStateTransitionError(HandGameException):
    """Rzucany, gdy następuje próba nielegalnej zmiany stanu sesji."""
    pass