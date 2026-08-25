class HandGameException(Exception):
    """Base exception for the HandGame app."""
    pass

class InvalidStateTransitionError(HandGameException):
    """Raised on an illegal session state transition."""
    pass