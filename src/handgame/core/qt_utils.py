"""Małe, współdzielone narzędzia Qt dla bezpiecznego zamykania wątków.

QThread.wait() blokuje wątek wywołujący bez pompowania jego pętli zdarzeń.
Gdy zatrzymanie workera zależy od crossthreadowego QueuedConnection
(worker.finished -> thread.quit), zwykłe wait(timeout_ms) w wątku głównym
NIGDY nie pozwoli tej kolejce się wykonać - wait() zawsze czeka pełny
timeout, mimo że worker skończył pracę dawno temu. wait_for_thread_stopped()
naprzemiennie pompuje zdarzenia i odpytuje wątek, więc zamknięcie kończy się
tak szybko, jak faktycznie się zatrzyma.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QThread


def wait_for_thread_stopped(thread: QThread, timeout_ms: int, poll_ms: int = 10) -> bool:
    """Czeka aż `thread` faktycznie się zatrzyma, pompując przy tym zdarzenia
    wątku wywołującego (żeby zakolejkowane thread.quit() miało szansę się wykonać).

    Zwraca True jeśli wątek zatrzymał się przed upływem timeout_ms.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while thread.isRunning():
        QCoreApplication.processEvents()
        if thread.wait(poll_ms):
            return True
        if time.monotonic() >= deadline:
            return False
    return True
