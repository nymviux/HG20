import logging
from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCore import Slot

from handgame.core.events import (
    ApplicationErrorEvent,
    FramePacket,
    GestureRecognitionEvent,
    InferenceStatusEvent,
)
from handgame.core.models import InferenceState, PlayerId, Severity, SourceType

from .inference_worker import BaseInferenceWorker

logger = logging.getLogger(__name__)


@dataclass
class MockResultSpec:
    """Deterministyczny wynik do wstrzyknięcia w testach przez configure_mock_result()."""

    recognized_sign: str | None = None
    confidence: float = 0.95
    is_correct: bool | None = None
    is_error: bool = False
    error_message: str = "Simulated inference error"


class MockInferenceWorker(BaseInferenceWorker):

    def __init__(self, camera_id, algorithm_id):
        super().__init__(camera_id, algorithm_id)
        self._state = InferenceState.IDLE
        self._result_queue: list[MockResultSpec] = []

    def _set_state(self, new_state: InferenceState, msg: str = ""):
        old = self._state
        self._state = new_state
        self.status_changed.emit(
            InferenceStatusEvent(self.algorithm_id, old, new_state, self.camera_id, msg)
        )

    @Slot()
    def start(self) -> None:
        self._set_state(InferenceState.STARTING)
        # Symulacja natychmiastowej gotowości (w prod tu ładujemy model)
        self._set_state(InferenceState.READY)
        logger.info(f"Inference worker {self.camera_id} ready.")

    @Slot()
    def stop(self) -> None:
        self._set_state(InferenceState.STOPPING)
        self._set_state(InferenceState.IDLE)
        self.finished.emit(self.camera_id)
        logger.info(f"Inference worker {self.camera_id} stopped.")

    @Slot(object)
    def configure_mock_result(self, spec: MockResultSpec) -> None:
        """Test-only hook: enqueue a deterministic result consumed FIFO by submit_frame."""
        self._result_queue.append(spec)

    @Slot(object)
    def submit_frame(self, packet: FramePacket) -> None:
        """Prosta symulacja - w prod to będzie blokujący model AI."""
        if self._state not in (InferenceState.READY, InferenceState.PROCESSING):
            return

        self._set_state(InferenceState.PROCESSING)

        if self._result_queue:
            spec = self._result_queue.pop(0)
            if spec.is_error:
                self._set_state(InferenceState.ERROR, spec.error_message)
                self.error_occurred.emit(
                    ApplicationErrorEvent(
                        source=SourceType.INFERENCE,
                        severity=Severity.ERROR,
                        code="INF_MOCK_ERR",
                        message=spec.error_message,
                        recoverable=True,
                        camera_id=self.camera_id,
                    )
                )
                self._set_state(InferenceState.READY)
                return
            rec_sign = spec.recognized_sign
            confidence = spec.confidence
            is_correct = spec.is_correct
        else:
            # Domyślne zachowanie (bez konfiguracji) - niezmienione względem poprzedniej wersji.
            rec_sign = self.expected_sign if self.expected_sign else "A"
            is_correct = (rec_sign == self.expected_sign) if self.expected_sign else None
            confidence = 0.95

        result = GestureRecognitionEvent(
            session_id=self.current_session or uuid4(),
            player_id=packet.player_id or self.current_player or PlayerId.PLAYER_1,  # Fallback
            camera_id=packet.camera_id,
            algorithm_id=self.algorithm_id,
            # "" oznacza "brak oczekiwanego znaku" (patrz set_expected_sign) - event
            # dataclass zabrania pustego stringa, więc mapujemy na None.
            expected_sign=self.expected_sign or None,
            recognized_sign=rec_sign,
            confidence=confidence,
            is_correct=is_correct,
            latency_ms=12.5,
        )

        self.gesture_recognized.emit(result)
        self._set_state(InferenceState.READY)
