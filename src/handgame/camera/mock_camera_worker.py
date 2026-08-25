import logging

from PySide6.QtCore import QTimer, Slot

from handgame.core.events import ApplicationErrorEvent, CameraStatusEvent, FramePacket
from handgame.core.models import CameraId, CameraState, PlayerId, Severity, SourceType

from .camera_worker import BaseCameraWorker

logger = logging.getLogger(__name__)


class MockCameraWorker(BaseCameraWorker):
    """Worker udający sprzęt wideo. Emituje "puste" ramki w stałych odstępach."""

    def __init__(self, camera_id: CameraId, player_id: PlayerId | None = None, fps: int = 30):
        super().__init__(camera_id)
        self.player_id = player_id
        self._fps = fps
        self._frame_count = 0
        self._timer: QTimer | None = None
        self._state = CameraState.DISCONNECTED

    def _set_state(self, new_state: CameraState, msg: str = ""):
        old_state = self._state
        self._state = new_state
        self.status_changed.emit(
            CameraStatusEvent(self.camera_id, old_state, new_state, self.player_id, msg)
        )

    @Slot()
    def start_stream(self) -> None:
        self._set_state(CameraState.CONNECTING, "Mock connecting...")
        # Inicjalizacja timera w obrębie poprawnego wątku (po moveToThread)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.emit_mock_frame)
        self._timer.start(1000 // self._fps)
        self._set_state(CameraState.READY)
        self._set_state(CameraState.STREAMING, "Mock stream started")
        logger.info(f"{self.camera_id} worker started.")

    @Slot()
    def stop_stream(self) -> None:
        self._set_state(CameraState.STOPPING, "Mock stopping...")
        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._set_state(CameraState.DISCONNECTED, "Mock disconnected")
        self.finished.emit(self.camera_id)
        logger.info(f"{self.camera_id} worker stopped.")

    @Slot()
    def restart_stream(self) -> None:
        self.stop_stream()
        self.start_stream()

    @Slot(object)
    def force_error(self, message: str) -> None:
        """Test-only hook: puts the worker into CameraState.ERROR without stopping it."""
        self._set_state(CameraState.ERROR, message)
        self.error_occurred.emit(
            ApplicationErrorEvent(
                source=SourceType.CAMERA,
                severity=Severity.ERROR,
                code="CAM_MOCK_ERR",
                message=message,
                recoverable=True,
                camera_id=self.camera_id,
            )
        )

    @Slot()
    def emit_mock_frame(self) -> None:
        """Metoda wywoływana przez timer lub ręcznie w testach."""
        if self._state != CameraState.STREAMING:
            return
        self._frame_count += 1
        packet = FramePacket(
            camera_id=self.camera_id,
            frame_id=self._frame_count,
            frame="MOCK_NDARRAY_DATA",
            player_id=self.player_id,
        )
        self.frame_captured.emit(packet)
