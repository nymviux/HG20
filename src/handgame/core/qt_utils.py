"""Shared Qt helpers for safe thread shutdown.

QThread.wait() blocks the caller without pumping its event loop. If worker
shutdown relies on a cross-thread QueuedConnection (worker.finished ->
thread.quit), wait(timeout_ms) on the main thread never lets that queued
call run - it always blocks the full timeout even though the worker finished
long ago. wait_for_thread_stopped() alternates pumping events and polling
the thread, so shutdown completes as soon as the thread actually stops.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QThread


def wait_for_thread_stopped(thread: QThread, timeout_ms: int, poll_ms: int = 10) -> bool:
    """Waits for `thread` to stop, pumping the caller's event loop so a
    queued thread.quit() can run.

    Returns True if the thread stopped before timeout_ms elapsed.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while thread.isRunning():
        QCoreApplication.processEvents()
        if thread.wait(poll_ms):
            return True
        if time.monotonic() >= deadline:
            return False
    return True
