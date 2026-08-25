"""Typed models opisujące kontekst i parametry trudności minigry.

Wartości domyślne w ``DIFFICULTY_PRESETS`` są placeholderem do dostrojenia
przez zespół projektującym balans gry - nie są wynikiem żadnych testów
rozgrywki.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import UUID

from handgame.core.models import CameraId, GameMode, PlayerId


@dataclass(frozen=True)
class DifficultyProfile:
    """Parametry trudności pojedynczej rozgrywki. Poziom 1-5."""

    level: int
    gesture_timeout_ms: int
    hint_delay_ms: int
    hint_duration_ms: int
    sequence_length: int
    board_size: int
    allowed_mistakes: int
    speed_multiplier: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (1 <= self.level <= 5):
            raise ValueError("Difficulty level musi być w przedziale 1-5")
        for field_name in (
            "gesture_timeout_ms",
            "hint_delay_ms",
            "hint_duration_ms",
            "sequence_length",
            "board_size",
            "allowed_mistakes",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} nie może być ujemne")
        if self.speed_multiplier <= 0:
            raise ValueError("speed_multiplier musi być dodatnie")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


# Placeholder game-balance numbers - do dostrojenia przez projektanta gry.
DIFFICULTY_PRESETS: Mapping[int, DifficultyProfile] = {
    1: DifficultyProfile(1, 8000, 3000, 2000, 3, 3, 3, 0.8),
    2: DifficultyProfile(2, 6000, 2500, 1800, 3, 3, 2, 0.9),
    3: DifficultyProfile(3, 5000, 2000, 1500, 4, 4, 2, 1.0),
    4: DifficultyProfile(4, 4000, 1500, 1200, 4, 4, 1, 1.2),
    5: DifficultyProfile(5, 3000, 1000, 800, 5, 5, 1, 1.5),
}


def build_difficulty_profile(level: int) -> DifficultyProfile:
    """Buduje DifficultyProfile dla podanego poziomu (1-5) z presetu."""
    if level not in DIFFICULTY_PRESETS:
        raise ValueError("Difficulty level musi być w przedziale 1-5")
    return DIFFICULTY_PRESETS[level]


@dataclass(frozen=True)
class PlayerGameState:
    """Migawka stanu jednego gracza w trakcie minigry."""

    player_id: PlayerId
    score: int = 0
    mistakes: int = 0
    hint_count: int = 0
    current_step: int = 0
    is_active: bool = True

    def __post_init__(self) -> None:
        for field_name in ("score", "mistakes", "hint_count", "current_step"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} nie może być ujemne")


@dataclass(frozen=True)
class GameContext:
    """Wszystko czego minigra potrzebuje do startu - dostarczane przez SessionManager."""

    session_id: UUID
    game_id: str
    mode: GameMode
    difficulty: DifficultyProfile
    player_camera_mapping: Mapping[PlayerId, CameraId]
    selected_algorithms: Mapping[CameraId, str]
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "player_camera_mapping", MappingProxyType(dict(self.player_camera_mapping))
        )
        object.__setattr__(
            self, "selected_algorithms", MappingProxyType(dict(self.selected_algorithms))
        )
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))
