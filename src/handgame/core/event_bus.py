from PySide6.QtCore import QObject, Signal

from .events import (
    ApplicationErrorEvent, CameraStatusEvent, 
    InferenceStatusEvent, SessionStatusEvent
)

class EventBus(QObject):
    """Centralny punkt diagnostyczny. Nie zastępuje typowanych sygnałów między menedżerami."""
    global_error = Signal(ApplicationErrorEvent)
    camera_status_changed = Signal(CameraStatusEvent)
    inference_status_changed = Signal(InferenceStatusEvent)
    session_status_changed = Signal(SessionStatusEvent)