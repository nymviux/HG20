"""Result of a finished minigame."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Any
from uuid import UUID

from handgame.core.models import GameState, PlayerId
from handgame.games.game_context import PlayerGameState


class GameEndReason(Enum):
    COMPLETED = auto()
    TIMEOUT = auto()
    ABORTED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class GameResult:
    """Frozen result of a single game, ready to pass to StatsSink."""

    session_id: UUID
    game_id: str
    final_state: GameState
    end_reason: GameEndReason
    player_results: Mapping[PlayerId, PlayerGameState]
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms nie może być ujemne")
        object.__setattr__(self, "player_results", MappingProxyType(dict(self.player_results)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
