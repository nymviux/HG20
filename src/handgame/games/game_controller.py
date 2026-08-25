"""Qt-owa granica między czystą logiką BaseGame a resztą aplikacji.

GameController tworzy/kończy minigry z rejestru, przekazuje im GestureRecognitionEvent,
implementuje GameEventSink (strukturalnie, bez dziedziczenia) i tłumaczy jego wywołania
na sygnały Qt konsumowane przez SessionManager. Buduje też SessionMetricsEvent po każdym
geście - to zachowanie sesyjne wspólne dla wszystkich minigier, nie logika jednej gry.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from handgame.core.events import (
    ApplicationErrorEvent,
    GameActionEvent,
    GestureRecognitionEvent,
    SessionMetricsEvent,
)
from handgame.core.models import GameState, PlayerId, Severity, SourceType
from handgame.games.base_game import BaseGame
from handgame.games.example_gesture_game import ExampleGestureGame
from handgame.games.game_context import GameContext, PlayerGameState
from handgame.games.game_result import GameEndReason, GameResult

logger = logging.getLogger(__name__)

# Rejestr dostępnych minigier. Nowa minigra = jeden wpis tutaj.
GAME_REGISTRY: dict[str, type[BaseGame]] = {
    ExampleGestureGame.GAME_ID: ExampleGestureGame,
}


class GameController(QObject):
    """Tworzy i steruje aktywną minigrą; jedyny punkt styku SessionManager <-> BaseGame."""

    game_action_ready = Signal(object)  # GameActionEvent
    metrics_ready = Signal(object)  # SessionMetricsEvent
    game_finished = Signal(object)  # GameResult
    game_error = Signal(object)  # ApplicationErrorEvent
    game_state_changed = Signal(object)  # GameState
    score_changed = Signal(object)  # PlayerGameState
    hint_requested = Signal(object)  # tuple[PlayerId, str]

    def __init__(self) -> None:
        super().__init__()
        self._game: BaseGame | None = None
        self._context: GameContext | None = None

    def create_game(self, game_id: str, context: GameContext) -> None:
        game_cls = GAME_REGISTRY.get(game_id)
        if game_cls is None:
            self._emit_error(f"Unknown game_id: {game_id}", recoverable=False)
            raise KeyError(game_id)
        self._game = game_cls(self)
        self._context = context
        self._game.start(context)

    def handle_gesture(self, event: GestureRecognitionEvent) -> None:
        if self._game is None or self._context is None:
            logger.warning("Gesture event ignored - no active game")
            return
        self._game.handle_gesture(event)
        try:
            player_state = self._game.get_player_state(event.player_id)
        except KeyError:
            return
        metrics = SessionMetricsEvent(
            session_id=event.session_id,
            game_id=self._context.game_id,
            difficulty_level=self._context.difficulty.level,
            player_id=event.player_id,
            score=player_state.score,
            mistakes=player_state.mistakes,
            hint_count=player_state.hint_count,
            reaction_time_ms=event.latency_ms,
        )
        self.metrics_ready.emit(metrics)

    def use_hint(self, player_id: PlayerId) -> None:
        if self._game is not None:
            self._game.use_hint(player_id)

    def pause(self) -> None:
        if self._game is not None:
            self._game.pause()

    def resume(self) -> None:
        if self._game is not None:
            self._game.resume()

    def reset(self) -> None:
        if self._game is not None:
            self._game.reset()
        self._game = None
        self._context = None

    def end(self, reason: GameEndReason = GameEndReason.ABORTED) -> GameResult | None:
        if self._game is None:
            return None
        existing = self._game.get_result()
        if existing is not None:
            return existing
        return self._game.end(reason)

    def get_state(self) -> GameState | None:
        return self._game.get_state() if self._game is not None else None

    def get_expected_sign(self, player_id: PlayerId) -> str | None:
        return self._game.get_expected_sign(player_id) if self._game is not None else None

    # --- GameEventSink protocol (implementowane strukturalnie, bez dziedziczenia) ---

    def on_state_changed(self, state: GameState) -> None:
        self.game_state_changed.emit(state)

    def on_score_changed(self, player_state: PlayerGameState) -> None:
        self.score_changed.emit(player_state)

    def on_hint_requested(self, player_id: PlayerId, hint: str) -> None:
        self.hint_requested.emit((player_id, hint))

    def on_action_ready(self, action: GameActionEvent) -> None:
        self.game_action_ready.emit(action)

    def on_finished(self, result: GameResult) -> None:
        self.game_finished.emit(result)

    def on_error(self, message: str, recoverable: bool) -> None:
        self._emit_error(message, recoverable)

    def _emit_error(self, message: str, recoverable: bool) -> None:
        logger.error("Game error: %s", message)
        self.game_error.emit(
            ApplicationErrorEvent(
                source=SourceType.GAME,
                severity=Severity.ERROR,
                code="GAME_ERR",
                message=message,
                recoverable=recoverable,
            )
        )
