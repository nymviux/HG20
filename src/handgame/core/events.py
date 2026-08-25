from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from .models import (
    CameraId,
    CameraState,
    InferenceState,
    PlayerId,
    SessionState,
    Severity,
    SourceType,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class FramePacket:
    camera_id: CameraId
    frame_id: int
    frame: Any  # e.g. np.ndarray; do not persist to disk/stats
    player_id: PlayerId | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class GestureRecognitionEvent:
    session_id: UUID
    player_id: PlayerId
    camera_id: CameraId
    algorithm_id: str
    event_id: UUID = field(default_factory=uuid4)
    expected_sign: str | None = None
    recognized_sign: str | None = None
    confidence: float | None = None
    is_correct: bool | None = None
    latency_ms: float | None = None
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Confidence musi być w przedziale 0.0 - 1.0")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("Latency nie może być ujemne")
        if self.recognized_sign == "":
            raise ValueError("Recognized sign nie może być pustym stringiem")
        if self.expected_sign == "":
            raise ValueError("Expected sign nie może być pustym stringiem")


@dataclass(frozen=True)
class CameraStatusEvent:
    camera_id: CameraId
    previous_state: CameraState
    current_state: CameraState
    player_id: PlayerId | None = None
    message: str | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class InferenceStatusEvent:
    algorithm_id: str
    previous_state: InferenceState
    current_state: InferenceState
    camera_id: CameraId | None = None
    message: str | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class SessionStatusEvent:
    session_id: UUID
    previous_state: SessionState
    current_state: SessionState
    message: str | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class ApplicationErrorEvent:
    source: SourceType
    severity: Severity
    code: str
    message: str
    recoverable: bool
    event_id: UUID = field(default_factory=uuid4)
    camera_id: CameraId | None = None
    player_id: PlayerId | None = None
    exception_type: str | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class GameActionEvent:
    session_id: UUID
    player_id: PlayerId
    action_type: str
    payload: Mapping[str, Any]
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        # Payload frozen after creation - receiver can't mutate it.
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class SessionMetricsEvent:
    session_id: UUID
    game_id: str
    difficulty_level: int
    player_id: PlayerId | None = None
    score: int | None = None
    mistakes: int | None = None
    hint_count: int | None = None
    reaction_time_ms: float | None = None
    timestamp: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        if not (1 <= self.difficulty_level <= 5):
            raise ValueError("Difficulty level musi być w przedziale 1-5")
        if self.reaction_time_ms is not None and self.reaction_time_ms < 0:
            raise ValueError("Reaction time nie może być ujemne")
