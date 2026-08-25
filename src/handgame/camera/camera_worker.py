from PySide6.QtCore import QObject, Signal

from handgame.core.models import CameraId


class BaseCameraWorker(QObject):
    """
    Abstract base for camera workers. Must run in its own QThread; must not block the GUI.

    All signals carry Signal(object) - actual payload type is documented at
    the emission site (see docs/gui_camera_ai_contract.md).
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
        """Mock-only: force worker into CameraState.ERROR. Real hardware workers may leave unimplemented."""
        raise NotImplementedError
