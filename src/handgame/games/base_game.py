"""Common contract for all HandGame 2.0 minigames.

``BaseGame`` is pure domain logic - no Qt, no camera/AI/GUI access. All
external communication goes through the injected ``GameEventSink`` (see
``docs/game_framework.md``). The Qt layer (Signal/Slot) is added only by
``GameController``.

``handle_gesture`` is a concrete template method: it runs state/player/
session filtering once, leaving actual recognition logic to the abstract
``_on_gesture`` hook, so new minigames don't duplicate guard boilerplate.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from handgame.core.events import GameActionEvent, GestureRecognitionEvent
from handgame.core.models import GameState, PlayerId
from handgame.games.game_context import GameContext, PlayerGameState
from handgame.games.game_result import GameEndReason, GameResult

logger = logging.getLogger(__name__)

# Legal minigame state transitions. Any other jump is rejected.
_ALLOWED_TRANSITIONS: dict[GameState, frozenset[GameState]] = {
    GameState.CREATED: frozenset({GameState.READY, GameState.ERROR}),
    GameState.READY: frozenset({GameState.RUNNING, GameState.ERROR}),
    GameState.RUNNING: frozenset({GameState.PAUSED, GameState.FINISHED, GameState.ERROR}),
    GameState.PAUSED: frozenset({GameState.RUNNING, GameState.FINISHED, GameState.ERROR}),
    GameState.FINISHED: frozenset(),
    GameState.ERROR: frozenset(),
}


class GameEventSink(Protocol):
    """Channel BaseGame uses to communicate externally (no Qt)."""

    def on_state_changed(self, state: GameState) -> None: ...

    def on_score_changed(self, player_state: PlayerGameState) -> None: ...

    def on_hint_requested(self, player_id: PlayerId, hint: str) -> None: ...

    def on_action_ready(self, action: GameActionEvent) -> None: ...

    def on_finished(self, result: GameResult) -> None: ...

    def on_error(self, message: str, recoverable: bool) -> None: ...


class BaseGame(ABC):
    """Abstract minigame base. Imports no QtWidgets or Qt module."""

    def __init__(self, event_sink: GameEventSink) -> None:
        self._sink = event_sink
        self._state: GameState = GameState.CREATED
        self._context: GameContext | None = None
        self._players: dict[PlayerId, PlayerGameState] = {}
        self._result: GameResult | None = None
        self._started_at: datetime | None = None

    # --- Required minigame contract ---

    @abstractmethod
    def start(self, context: GameContext) -> None:
        """Initializes the minigame from GameContext and enters RUNNING."""

    @abstractmethod
    def update_frame(self, delta_ms: float) -> None:
        """Called periodically (e.g. timeouts/hints). No camera/AI logic."""

    @abstractmethod
    def end(self, reason: GameEndReason = GameEndReason.COMPLETED) -> GameResult:
        """Ends the game and returns GameResult. Must call self._finalize(reason)."""

    @abstractmethod
    def _on_gesture(self, event: GestureRecognitionEvent) -> None:
        """Actual game logic after handle_gesture's state/player/session filters."""

    # --- Concrete implementation shared by all minigames ---

    def handle_gesture(self, event: GestureRecognitionEvent) -> None:
        if self._state != GameState.RUNNING:
            logger.warning("Gesture event ignored - game not RUNNING (state=%s)", self._state)
            self._sink.on_error("Gesture event received before game started.", recoverable=True)
            return
        if self._context is None or event.session_id != self._context.session_id:
            logger.warning("Gesture event ignored - session_id mismatch")
            self._sink.on_error("Gesture event from unknown session.", recoverable=True)
            return
        if event.player_id not in self._players:
            logger.warning("Gesture event ignored - unknown player %s", event.player_id)
            self._sink.on_error("Gesture event from unknown player.", recoverable=True)
            return
        expected_camera = self._context.player_camera_mapping.get(event.player_id)
        if expected_camera is not None and event.camera_id != expected_camera:
            logger.warning("Gesture event ignored - camera/player mismatch")
            self._sink.on_error("Gesture event from unexpected camera.", recoverable=True)
            return
        self._on_gesture(event)

    def pause(self) -> None:
        if self._state != GameState.RUNNING:
            logger.warning("pause() ignored - game not RUNNING (state=%s)", self._state)
            self._sink.on_error("Cannot pause a game that is not running.", recoverable=True)
            return
        self._transition(GameState.PAUSED)

    def resume(self) -> None:
        if self._state != GameState.PAUSED:
            logger.warning("resume() ignored - game not PAUSED (state=%s)", self._state)
            self._sink.on_error("Cannot resume a game that is not paused.", recoverable=True)
            return
        self._transition(GameState.RUNNING)

    def reset(self) -> None:
        """Hard reset - allowed from any state, preps game for next session."""
        self._context = None
        self._players = {}
        self._result = None
        self._started_at = None
        self._state = GameState.CREATED
        self._sink.on_state_changed(self._state)

    def use_hint(self, player_id: PlayerId) -> None:
        if player_id not in self._players:
            logger.warning("use_hint() ignored - unknown player %s", player_id)
            return
        current = self._players[player_id]
        updated = replace(current, hint_count=current.hint_count + 1)
        self._players[player_id] = updated
        self._sink.on_hint_requested(player_id, self.get_expected_sign(player_id) or "")

    def get_state(self) -> GameState:
        return self._state

    def get_result(self) -> GameResult | None:
        return self._result

    def get_expected_sign(self, player_id: PlayerId) -> str | None:
        """No hint by default; fixed-sequence minigames override this."""
        return None

    def get_player_state(self, player_id: PlayerId) -> PlayerGameState:
        return self._players[player_id]

    # --- Protected helper methods for subclasses ---

    def _transition(self, new_state: GameState) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self._state, frozenset())
        if new_state not in allowed:
            logger.error("Illegal game state transition %s -> %s", self._state, new_state)
            self._sink.on_error(
                f"Illegal game state transition {self._state.name} -> {new_state.name}",
                recoverable=False,
            )
            return
        self._state = new_state
        self._sink.on_state_changed(new_state)

    def _begin(self, context: GameContext) -> None:
        """CREATED -> READY: stores context, inits player state."""
        self._context = context
        self._started_at = datetime.now(UTC)
        self._players = {
            player_id: PlayerGameState(player_id=player_id)
            for player_id in context.player_camera_mapping
        }
        self._result = None
        self._transition(GameState.READY)

    def _enter_running(self) -> None:
        """READY -> RUNNING."""
        self._transition(GameState.RUNNING)

    def _update_player(self, player_id: PlayerId, **changes: object) -> PlayerGameState:
        current = self._players[player_id]
        updated = replace(current, **changes)  # type: ignore[arg-type]
        self._players[player_id] = updated
        self._sink.on_score_changed(updated)
        return updated

    def _finalize(self, reason: GameEndReason) -> GameResult:
        """Builds GameResult, transitions to FINISHED, notifies sink. Idempotent."""
        if self._result is not None:
            return self._result
        if self._context is None:
            raise RuntimeError("Cannot finalize a game that was never started().")
        finished_at = datetime.now(UTC)
        started_at = self._started_at or finished_at
        duration_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
        final_state = GameState.ERROR if reason == GameEndReason.ERROR else GameState.FINISHED
        if self._state in (GameState.RUNNING, GameState.PAUSED):
            self._transition(final_state)
        result = GameResult(
            session_id=self._context.session_id,
            game_id=self._context.game_id,
            final_state=final_state,
            end_reason=reason,
            player_results=dict(self._players),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        self._result = result
        self._sink.on_finished(result)
        return result
