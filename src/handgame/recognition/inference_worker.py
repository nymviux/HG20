from uuid import UUID

from PySide6.QtCore import QObject, Signal, Slot

from handgame.core.events import (
    FramePacket,
    InferenceStatusEvent,
)
from handgame.core.models import CameraId, InferenceState, PlayerId


class BaseInferenceWorker(QObject):
    gesture_recognized = Signal(object)  # GestureRecognitionEvent
    status_changed = Signal(object)  # InferenceStatusEvent
    error_occurred = Signal(object)  # ApplicationErrorEvent
    finished = Signal(object)  # CameraId

    def __init__(self, camera_id: CameraId, algorithm_id: str):
        super().__init__()
        self.camera_id = camera_id
        self.algorithm_id = algorithm_id
        self.current_session: UUID | None = None
        self.current_player: PlayerId | None = None
        self.expected_sign: str | None = None

    @Slot()
    def start(self) -> None:
        raise NotImplementedError

    @Slot()
    def stop(self) -> None:
        self.status_changed.emit(
            InferenceStatusEvent(
                algorithm_id=self.algorithm_id,
                previous_state=InferenceState.READY,
                current_state=InferenceState.STOPPING,
                camera_id=self.camera_id,
                message="Stopping mock inference worker",
            )
        )

        self.finished.emit(self.camera_id)

    @Slot(object)
    def submit_frame(self, packet: FramePacket) -> None:
        raise NotImplementedError

    @Slot(str, str, str)
    def set_expected_sign(self, session_id: str, player_id: str, expected_sign: str) -> None:
        self.current_session = UUID(session_id) if session_id else None
        # Proste rzutowanie stringa na Enum w QObject Slot
        for p in PlayerId:
            if p.name == player_id:
                self.current_player = p
                break
        self.expected_sign = expected_sign
