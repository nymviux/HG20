from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from handgame.core.events import CameraStatusEvent
from handgame.core.models import CameraId, CameraState, PlayerId
from handgame.core.qt_utils import wait_for_thread_stopped

from .mock_camera_worker import MockCameraWorker

logger = logging.getLogger(__name__)


class CameraWorkerHandle(QObject):
    """
    Proxy żyjący w głównym/menedżerskim wątku.
    Sygnały są bezpiecznie przekazywane do workera w jego QThread przez QueuedConnection.
    """

    start_requested = Signal()
    stop_requested = Signal()
    restart_requested = Signal()
    force_error_requested = Signal(object)  # str message, test-only hook


@dataclass
class CameraRuntime:
    thread: QThread
    worker: MockCameraWorker
    handle: CameraWorkerHandle


class CameraManager(QObject):
    """Zarządza cyklem życia workerów obsługujących kamery."""

    frame_ready = Signal(object)  # FramePacket
    camera_status_changed = Signal(object)  # CameraStatusEvent
    error_occurred = Signal(object)  # ApplicationErrorEvent

    def __init__(self):
        super().__init__()
        self._runtimes: dict[CameraId, CameraRuntime] = {}
        self._states: dict[CameraId, CameraState] = {}

    def start_camera(self, camera_id: CameraId, player_id: PlayerId | None = None) -> None:
        if camera_id in self._runtimes:
            logger.warning(f"Kamera {camera_id} jest już uruchomiona.")
            return

        worker = MockCameraWorker(camera_id, player_id)
        # Bez rodzica: cykl życia w pełni kontrolowany przez finished -> deleteLater
        # poniżej. QThread(self) tworzyłby PODWÓJNĄ własność (kaskada rodzica C++
        # kontra osobno zakolejkowane deleteLater na tym samym obiekcie) - potencjalny
        # double-free, gdy CameraManager zostaje zniszczony zanim wątek zdąży się
        # posprzątać przez własną pętlę zdarzeń.
        thread = QThread()
        handle = CameraWorkerHandle()

        worker.moveToThread(thread)

        # Manager -> worker: zawsze QueuedConnection przez proxy handle.
        handle.start_requested.connect(worker.start_stream, Qt.ConnectionType.QueuedConnection)
        handle.stop_requested.connect(worker.stop_stream, Qt.ConnectionType.QueuedConnection)
        handle.restart_requested.connect(worker.restart_stream, Qt.ConnectionType.QueuedConnection)
        handle.force_error_requested.connect(worker.force_error, Qt.ConnectionType.QueuedConnection)

        # Cykl życia wątku.
        thread.started.connect(handle.start_requested, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        # Worker -> manager (dane).
        worker.frame_captured.connect(self.frame_ready)
        worker.status_changed.connect(self._on_worker_status_changed)
        worker.error_occurred.connect(self.error_occurred)

        # Sprzątanie dopiero gdy QThread naprawdę się zatrzyma.
        thread.finished.connect(lambda camera_id=camera_id: self._cleanup_runtime(camera_id))

        self._runtimes[camera_id] = CameraRuntime(thread=thread, worker=worker, handle=handle)
        self._states[camera_id] = CameraState.CONNECTING

        thread.start()

    def stop_camera(self, camera_id: CameraId) -> None:
        """
        Prosi worker o zatrzymanie. Nie usuwa referencji do QThread ani workera tutaj.
        Sprzątanie odbędzie się w _cleanup_runtime po thread.finished.
        """
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return

        if self._states.get(camera_id) == CameraState.STOPPING:
            return

        self._states[camera_id] = CameraState.STOPPING
        runtime.handle.stop_requested.emit()

    def restart_camera(self, camera_id: CameraId) -> None:
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return
        runtime.handle.restart_requested.emit()

    def force_camera_error(
        self, camera_id: CameraId, message: str = "Simulated camera error"
    ) -> None:
        """Test-only helper: forces the mock camera worker into CameraState.ERROR."""
        runtime = self._runtimes.get(camera_id)
        if runtime is None:
            return
        runtime.handle.force_error_requested.emit(message)

    def get_camera_state(self, camera_id: CameraId) -> CameraState:
        return self._states.get(camera_id, CameraState.DISCONNECTED)

    @Slot(object)
    def _on_worker_status_changed(self, event: CameraStatusEvent) -> None:
        self._states[event.camera_id] = event.current_state
        self.camera_status_changed.emit(event)

    def _cleanup_runtime(self, camera_id: CameraId) -> None:
        """Wywoływane dopiero po thread.finished - QThread na pewno już nie pracuje."""
        logger.info("Camera thread stopped for %s", camera_id)
        self._runtimes.pop(camera_id, None)
        self._states[camera_id] = CameraState.DISCONNECTED

    def shutdown(self, timeout_ms: int = 3_000) -> None:
        """Bezpieczne ubijanie przed wyjściem z aplikacji. Czeka na realne zatrzymanie wątków."""
        camera_ids = list(self._runtimes.keys())

        for camera_id in camera_ids:
            self.stop_camera(camera_id)

        for camera_id in camera_ids:
            runtime = self._runtimes.get(camera_id)
            if runtime is None:
                continue
            if not wait_for_thread_stopped(runtime.thread, timeout_ms):
                logger.error("Camera thread did not stop in %s ms: %s", timeout_ms, camera_id)
                # Awaryjne opuszczenie event loop, bez thread.terminate().
                runtime.thread.quit()
                runtime.thread.wait(1_000)

        # W przypadku testów bez pełnej pętli zdarzeń Qt finished może nie zdążyć
        # wywołać _cleanup_runtime.
        for camera_id in list(self._runtimes.keys()):
            runtime = self._runtimes[camera_id]
            if not runtime.thread.isRunning():
                self._cleanup_runtime(camera_id)
