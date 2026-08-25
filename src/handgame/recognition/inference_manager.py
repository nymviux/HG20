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
    """Proxy living in the main thread; signals are safely marshalled to the worker in its QThread."""

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
        """Creates and starts a dedicated AI worker for the given camera."""
        if camera_id in self._runtimes:
            logger.warning("Inference worker already exists for %s", camera_id)
            return

        worker = MockInferenceWorker(camera_id=camera_id, algorithm_id=algorithm_id)
        # No parent: lifecycle fully controlled via finished -> deleteLater below.
        # QThread(self) would create DOUBLE ownership (C++ parent cascade vs a
        # separately queued deleteLater on the same object) - risk of double-free
        # if InferenceManager is destroyed before the thread's own event loop
        # finishes cleanup.
        thread = QThread()
        handle = InferenceWorkerHandle()

        worker.moveToThread(thread)

        # Manager -> worker: always QueuedConnection.
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

        # Thread lifecycle.
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

        # Cleanup only after QThread actually stops.
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
        """Requests the worker to stop. Does not remove QThread/worker refs here;
        cleanup happens in _cleanup_runtime after thread.finished."""
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
        """Latest frame wins: if the worker is still processing the previous frame, this one is dropped."""
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

            # On AI error, unblock any pending wait for a result.
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
        """Called only after thread.finished; QThread is no longer running, so refs can be removed."""
        logger.info("Inference thread stopped for %s", camera_id)

        self._runtimes.pop(camera_id, None)
        self._states.pop(camera_id, None)
        self._is_busy.pop(camera_id, None)

    def shutdown(self, timeout_ms: int = 3_000) -> None:
        """Safely stops all workers. Worker emits finished -> thread.quit -> thread.finished;
        wait() then confirms the actual stop."""
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
                # Fallback: force event loop exit, without thread.terminate().
                runtime.thread.quit()
                runtime.thread.wait(1_000)

        # In tests without a full Qt event loop, finished may not
        # fire _cleanup_runtime in time.
        for camera_id in list(self._runtimes.keys()):
            runtime = self._runtimes[camera_id]
            if not runtime.thread.isRunning():
                self._cleanup_runtime(camera_id)
