from PySide6.QtCore import QObject, Signal

from handgame.core.models import CameraId


class BaseCameraWorker(QObject):
    """
    Abstrakcyjna baza dla workerów kamer.
    Musi działać w osobnym QThread. Nie może blokować GUI.

    Wszystkie sygnały niosą Signal(object) - konkretny typ payloadu jest
    udokumentowany przy miejscu emisji (patrz docs/gui_camera_ai_contract.md).
    """

    frame_captured = Signal(object)  # FramePacket
    status_changed = Signal(object)  # CameraStatusEvent
    error_occurred = Signal(object)  # ApplicationErrorEvent
    finished = Signal(object)  # CameraId

    def __init__(self, camera_id: CameraId):
        super().__init__()
        self.camera_id = camera_id

    def start_stream(self) -> None:
        raise NotImplementedError

    def stop_stream(self) -> None:
        raise NotImplementedError

    def restart_stream(self) -> None:
        raise NotImplementedError

    def force_error(self, message: str) -> None:
        """Mock-only capability: force the worker into CameraState.ERROR. Real hardware
        workers may leave this unimplemented."""
        raise NotImplementedError
