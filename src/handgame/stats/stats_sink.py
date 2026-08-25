import logging

from PySide6.QtCore import QObject, Slot

from handgame.core.events import GestureRecognitionEvent, SessionMetricsEvent
from handgame.games.game_result import GameResult

logger = logging.getLogger(__name__)


class StatsSink(QObject):
    """Records GDPR-safe stats only; never stores images.

    Each method extracts only named fields (never vars(event)/__dict__), so
    frame/image/video data can't leak in here even if later added to these
    event types.
    """

    def __init__(self):
        super().__init__()
        self._in_memory_db = []
        self._gesture_log = []
        self._results_log = []

    @Slot(SessionMetricsEvent)
    def record_metrics(self, event: SessionMetricsEvent):
        record = {
            "session_id": str(event.session_id),
            "game_id": event.game_id,
            "difficulty": event.difficulty_level,
            "player_id": event.player_id.name if event.player_id else None,
            "timestamp": event.timestamp.isoformat(),
            "reaction_time_ms": event.reaction_time_ms,
        }
        self._in_memory_db.append(record)
        logger.debug(f"Stats saved: {record}")

    @Slot(object)
    def record_gesture(self, event: GestureRecognitionEvent):
        record = {
            "event_id": str(event.event_id),
            "session_id": str(event.session_id),
            "player_id": event.player_id.name if event.player_id else None,
            "camera_id": event.camera_id.name if event.camera_id else None,
            "algorithm_id": event.algorithm_id,
            "expected_sign": event.expected_sign,
            "recognized_sign": event.recognized_sign,
            "confidence": event.confidence,
            "is_correct": event.is_correct,
            "latency_ms": event.latency_ms,
            "timestamp": event.timestamp.isoformat(),
        }
        self._gesture_log.append(record)
        logger.debug(f"Gesture stats saved: {record}")

    @Slot(object)
    def record_result(self, event: GameResult):
        record = {
            "session_id": str(event.session_id),
            "game_id": event.game_id,
            "final_state": event.final_state.name,
            "end_reason": event.end_reason.name,
            "player_results": {
                player_id.name: {
                    "score": state.score,
                    "mistakes": state.mistakes,
                    "hint_count": state.hint_count,
                }
                for player_id, state in event.player_results.items()
            },
            "started_at": event.started_at.isoformat(),
            "finished_at": event.finished_at.isoformat(),
            "duration_ms": event.duration_ms,
        }
        self._results_log.append(record)
        logger.debug(f"Result stats saved: {record}")
