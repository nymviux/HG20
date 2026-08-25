"""Reference minigame demonstrating the BaseGame API.

Each player gets a sequence of 3-5 expected signs (length from
DifficultyProfile.sequence_length). Correct gesture -> point + next step.
Wrong gesture -> mistake counter. Once all players finish their sequence,
the game ends automatically with GameEndReason.COMPLETED.

No camera or real AI model needed - fully testable in isolation.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from handgame.core.events import GameActionEvent, GestureRecognitionEvent
from handgame.core.models import PlayerId
from handgame.games.base_game import BaseGame, GameEventSink
from handgame.games.game_context import GameContext
from handgame.games.game_result import GameEndReason, GameResult

logger = logging.getLogger(__name__)

# Placeholder PJM sign pool - team to replace with real dictionary.
_SIGN_POOL: list[str] = ["A", "B", "C", "D", "E"]


class ExampleGestureGame(BaseGame):
    """Simple, fully testable "repeat the sequence" minigame."""

    GAME_ID: ClassVar[str] = "EXAMPLE_GESTURE_GAME"
    ACTION_TYPE_GESTURE_INPUT: ClassVar[str] = "GESTURE_INPUT"

    def __init__(self, event_sink: GameEventSink) -> None:
        super().__init__(event_sink)
        self._sequences: dict[PlayerId, list[str]] = {}

    def start(self, context: GameContext) -> None:
        self._begin(context)
        length = min(5, max(3, context.difficulty.sequence_length))
        self._sequences = {
            player_id: [_SIGN_POOL[i % len(_SIGN_POOL)] for i in range(length)]
            for player_id in context.player_camera_mapping
        }
        self._enter_running()

    def update_frame(self, delta_ms: float) -> None:
        # No time-based logic here (no timeouts/timed hints).
        pass

    def get_expected_sign(self, player_id: PlayerId) -> str | None:
        sequence = self._sequences.get(player_id)
        if not sequence:
            return None
        state = self._players.get(player_id)
        if state is None or state.current_step >= len(sequence):
            return None
        return sequence[state.current_step]

    def _on_gesture(self, event: GestureRecognitionEvent) -> None:
        expected = self.get_expected_sign(event.player_id)
        is_correct = expected is not None and event.recognized_sign == expected

        current = self._players[event.player_id]
        if is_correct:
            updated = self._update_player(
                event.player_id,
                score=current.score + 1,
                current_step=current.current_step + 1,
            )
        else:
            updated = self._update_player(event.player_id, mistakes=current.mistakes + 1)

        action = GameActionEvent(
            session_id=event.session_id,
            player_id=event.player_id,
            action_type=self.ACTION_TYPE_GESTURE_INPUT,
            payload={
                "sign": event.recognized_sign,
                "is_correct": is_correct,
                "confidence": event.confidence,
            },
        )
        self._sink.on_action_ready(action)

        sequence = self._sequences.get(event.player_id, [])
        if is_correct and updated.current_step >= len(sequence):
            all_done = all(
                self._players[p].current_step >= len(self._sequences.get(p, []))
                for p in self._players
            )
            if all_done:
                self.end(GameEndReason.COMPLETED)

    def end(self, reason: GameEndReason = GameEndReason.COMPLETED) -> GameResult:
        return self._finalize(reason)
