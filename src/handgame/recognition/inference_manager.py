from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from handgame.core.events import (
    ApplicationErrorEvent,
    FramePacket,
    GestureRecognitionEvent,
    InferenceStatusEvent,
)
from handgame.core.models import CameraId, InferenceState
from handgame.core.qt_utils import wait_for_thread_stopped
from handgame.recognition.mock_inference_worker import MockInferenceWorker, MockResultSpec

logger = logging.getLogger(__name__)


class InferenceWorkerHandle(QObject):
    """
    Proxy żyjący w głównym wątku.
    Sygnały są bezpiecznie przekazywane do workera w jego QThread.
    """

    start_requested = Signal()
    stop_requested = Signal()
    frame_requested = Signal(object)
    expected_sign_requested = Signal(str, str, str)
    configure_result_requested = Signal(object)  # MockResultSpec, mock-only test hook


@dataclass
class InferenceRuntime:
    thread: QThread
    worker: MockInferenceWorker
    handle: InferenceWorkerHandle


class InferenceManager(QObject):
    gesture_recognized = Signal(object)
    inference_status_changed = Signal(object)
    error_occurred = Signal(object)

    def __init__(self) -> None:
        super().__init__()

        self._runtimes: dict[CameraId, InferenceRuntime] = {}
        self._states: dict[CameraId, InferenceState] = {}
        self._is_busy: dict[CameraId, bool] = {}

    def start_algorithm(self, camera_id: CameraId, algorithm_id: str) -> None:
        """Tworzy i uruchamia osobny worker AI dla wskazanej kamery."""
        if camera_id in self._runtimes:
            logger.warning("Inference worker already exists for %s", camera_id)
            return

        worker = MockInferenceWorker(camera_id=camera_id, algorithm_id=algorithm_id)
        # Bez rodzica: cykl życia w pełni kontrolowany przez finished -> deleteLater
        # poniżej. QThread(self) tworzyłby PODWÓJNĄ własność (kaskada rodzica C++
        # kontra osobno zakolejkowane deleteLater na tym samym obiekcie) - potencjalny
        # double-free, gdy InferenceManager zostaje zniszczony zanim wątek zdąży się
        # posprzątać przez własną pętlę zdarzeń.
        thread = QThread()
        handle = InferenceWorkerHandle()

        worker.moveToThread(thread)

        # Manager -> worker: zawsze QueuedConnection.
        handle.start_requested.connect(
            worker.start,
            Qt.ConnectionType.QueuedConnection,
        )
        handle.stop_requested.connect(
            worker.stop,
            Qt.ConnectionType.QueuedConnection,
        )
        handle.frame_requested.connect(
            worker.submit_frame,
            Qt.ConnectionType.QueuedConnection,
        )
        handle.expected_sign_requested.connect(
            worker.set_expected_sign,
            Qt.ConnectionType.QueuedConnection,
        )
        handle.configure_result_requested.connect(
            worker.configure_mock_result,
            Qt.ConnectionType.QueuedConnection,
        )

        # Cykl życia wątku.
        thread.started.connect(
            handle.start_requested,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        # Worker -> manager.
        worker.gesture_recognized.connect(self._on_gesture_recognized)
        worker.status_changed.connect(self._on_status_changed)
        worker.error_occurred.connect(self._on_worker_error)

        # Sprzątanie dopiero gdy QThread naprawdę się zatrzyma.
        thread.finished.connect(lambda camera_id=camera_id: self._cleanup_runtime(camera_id))

        self._runtimes[camera_id] = InferenceRuntime(
            thread=thread,
            worker=worker,
            handle=handle,
        )
        self._states[camera_id] = InferenceState.STARTING
        self._is_busy[camera_id] = False

        thread.start()

    def is_algorithm_running(self, camera_id: CameraId) -> bool:
        return camera_id in self._runtimes

    def stop_algorithm(self, camera_id: CameraId) -> None:
        """
        Prosi worker o zatrzymanie.
        Nie usuwa referencji do QThread ani workera tutaj.
        Sprzątanie odbędzie się w _cleanup_runtime po thread.finished.
        """
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return

        current_state = self._states.get(camera_id)
        if current_state == InferenceState.STOPPING:
            return

        self._states[camera_id] = InferenceState.STOPPING
        runtime.handle.stop_requested.emit()

    @Slot(object)
    def process_frame(self, packet: FramePacket) -> None:
        """
        Latest frame wins:
        jeżeli worker nadal przetwarza poprzednią ramkę, bieżąca zostaje odrzucona.
        """
        camera_id = packet.camera_id
        runtime = self._runtimes.get(camera_id)

        if runtime is None:
            return

        if self._states.get(camera_id) != InferenceState.READY:
            return

        if self._is_busy.get(camera_id, False):
            return

        self._is_busy[camera_id] = True
        runtime.handle.frame_requested.emit(packet)

    def configure_mock_worker(self, camera_id: CameraId, spec: MockResultSpec) -> None:
        """Test-only helper: enqueue a deterministic MockResultSpec for a camera's worker."""
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return
        runtime.handle.configure_result_requested.emit(spec)

    def set_expected_sign(
        self,
        session_id: str,
        player_id: str,
        expected_sign: str,
        camera_id: CameraId,
    ) -> None:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return

        runtime.handle.expected_sign_requested.emit(
            session_id,
            player_id,
            expected_sign,
        )

    @Slot(object)
    def _on_gesture_recognized(self, event: GestureRecognitionEvent) -> None:
        self._is_busy[event.camera_id] = False
        self.gesture_recognized.emit(event)

    @Slot(object)
    def _on_status_changed(self, event: InferenceStatusEvent) -> None:
        if event.camera_id is not None:
            self._states[event.camera_id] = event.current_state

            # Przy błędzie AI odblokuj ewentualne oczekiwanie na wynik.
            if event.current_state == InferenceState.ERROR:
                self._is_busy[event.camera_id] = False

        self.inference_status_changed.emit(event)

    @Slot(object)
    def _on_worker_error(self, event: ApplicationErrorEvent) -> None:
        if event.camera_id is not None:
            self._is_busy[event.camera_id] = False
            self._states[event.camera_id] = InferenceState.ERROR

        logger.error(
            "Inference error: code=%s, message=%s",
            event.code,
            event.message,
        )
        self.error_occurred.emit(event)

    @Slot()
    def _cleanup_runtime(self, camera_id: CameraId) -> None:
        """
        Wywoływane dopiero po thread.finished.
        W tym momencie QThread nie pracuje, więc można usunąć referencje.

        """
        logger.info("Inference thread stopped for %s", camera_id)

        self._runtimes.pop(camera_id, None)
        self._states.pop(camera_id, None)
        self._is_busy.pop(camera_id, None)

    def shutdown(self, timeout_ms: int = 3_000) -> None:
        """
        Bezpieczne zatrzymanie wszystkich workerów.
        Worker sam emituje finished -> thread.quit -> thread.finished.
        Następnie wait() potwierdza faktyczne zatrzymanie.
        """
        camera_ids = list(self._runtimes.keys())

        for camera_id in camera_ids:
            self.stop_algorithm(camera_id)

        for camera_id in camera_ids:
            runtime = self._runtimes.get(camera_id)
            if runtime is None:
                continue

            if not wait_for_thread_stopped(runtime.thread, timeout_ms):
                logger.error(
                    "Inference thread did not stop in %s ms: %s",
                    timeout_ms,
                    camera_id,
                )
                # Awaryjne opuszczenie event loop, bez thread.terminate().
                runtime.thread.quit()
                runtime.thread.wait(1_000)

        # W przypadku testów bez pełnej pętli zdarzeń Qt
        # finished może nie zdążyć wywołać _cleanup_runtime.
        for camera_id in list(self._runtimes.keys()):
            runtime = self._runtimes[camera_id]
            if not runtime.thread.isRunning():
                self._cleanup_runtime(camera_id)
