import logging
from uuid import UUID, uuid4

from PySide6.QtCore import QObject, Signal, Slot

from handgame.core.errors import InvalidStateTransitionError
from handgame.core.events import (
    ApplicationErrorEvent,
    CameraStatusEvent,
    GestureRecognitionEvent,
    InferenceStatusEvent,
    SessionStatusEvent,
)
from handgame.core.models import (
    CameraId,
    CameraState,
    GameMode,
    InferenceState,
    PlayerId,
    SessionState,
    Severity,
    SourceType,
)
from handgame.games.game_context import DifficultyProfile, GameContext, build_difficulty_profile
from handgame.games.game_controller import GameController
from handgame.games.game_result import GameEndReason

logger = logging.getLogger(__name__)


class SessionManager(QObject):
    session_status_changed = Signal(SessionStatusEvent)
    game_action_ready = Signal(object)  # GameActionEvent
    metrics_ready = Signal(object)  # SessionMetricsEvent
    game_finished = Signal(object)  # GameResult
    error_occurred = Signal(ApplicationErrorEvent)
    # (session_id, player_id, camera_id, expected_sign | None) - GUIIntegrationController
    # forwards this to InferenceManager.set_expected_sign() for the next recognition step.
    expected_sign_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.session_id: UUID | None = None
        self._state = SessionState.IDLE
        self.game_id = ""
        self.difficulty = 1

        self._mode: GameMode = GameMode.SINGLEPLAYER
        self._difficulty_profile: DifficultyProfile | None = None
        self._player_camera_mapping: dict[PlayerId, CameraId] = {}
        self._selected_algorithms: dict[CameraId, str] = {}

        # Weryfikacja środowiska zewnętrznego
        self._sys_camera_ready = False
        self._sys_ai_ready = False

        self._game_controller = GameController()
        self._game_controller.game_action_ready.connect(self.game_action_ready)
        self._game_controller.metrics_ready.connect(self.metrics_ready)
        self._game_controller.game_finished.connect(self.game_finished)
        self._game_controller.game_error.connect(self.error_occurred)

    def _change_state(self, new_state: SessionState):
        old_state = self._state
        self._state = new_state
        if self.session_id:
            self.session_status_changed.emit(
                SessionStatusEvent(self.session_id, old_state, new_state)
            )
            logger.info(f"Session {self.session_id} state: {old_state.name} -> {new_state.name}")

    def prepare_session(
        self, game_id: str, difficulty: int, mode: GameMode = GameMode.SINGLEPLAYER
    ):
        if self._state not in (SessionState.IDLE, SessionState.FINISHED, SessionState.ERROR):
            raise InvalidStateTransitionError(
                f"Nie można przygotować z obecnego stanu: {self._state}"
            )

        self.session_id = uuid4()
        self.game_id = game_id
        self.difficulty = difficulty
        self._mode = mode
        self._difficulty_profile = build_difficulty_profile(difficulty)
        self._change_state(SessionState.PREPARING)

        # Opcjonalnie: Jeśli sprzęt jest już ready z poprzedniej gry
        self._check_auto_start()

    def register_camera_mapping(self, camera_id: CameraId, player_id: PlayerId) -> None:
        self._player_camera_mapping[player_id] = camera_id

    def register_algorithm_mapping(self, camera_id: CameraId, algorithm_id: str) -> None:
        self._selected_algorithms[camera_id] = algorithm_id

    def _check_auto_start(self):
        if self._state == SessionState.PREPARING and self._sys_camera_ready and self._sys_ai_ready:
            logger.info("Środowisko gotowe, sesja startuje automatycznie.")
            self.start_session()

    def start_session(self):
        if self._state != SessionState.PREPARING:
            return
        if not (self._sys_camera_ready and self._sys_ai_ready):
            self._emit_error("Moduły sprzętowe nie są gotowe do startu.")
            return
        if self._difficulty_profile is None or self.session_id is None:
            self._emit_error("Sesja nie została poprawnie przygotowana.")
            return

        context = GameContext(
            session_id=self.session_id,
            game_id=self.game_id,
            mode=self._mode,
            difficulty=self._difficulty_profile,
            player_camera_mapping=dict(self._player_camera_mapping),
            selected_algorithms=dict(self._selected_algorithms),
        )
        try:
            self._game_controller.create_game(self.game_id, context)
        except KeyError:
            self._emit_error(f"Nieznana minigra: {self.game_id}")
            return

        self._change_state(SessionState.RUNNING)
        self._push_expected_signs()

    def _push_expected_signs(self) -> None:
        """Przekazuje bieżący oczekiwany znak każdego gracza do InferenceManager
        (przez GUIIntegrationController, patrz expected_sign_ready)."""
        for player_id, camera_id in self._player_camera_mapping.items():
            sign = self._game_controller.get_expected_sign(player_id)
            self.expected_sign_ready.emit((self.session_id, player_id, camera_id, sign))

    def pause_session(self):
        if self._state != SessionState.RUNNING:
            return
        self._game_controller.pause()
        self._change_state(SessionState.PAUSED)

    def resume_session(self):
        if self._state != SessionState.PAUSED:
            return
        if not (self._sys_camera_ready and self._sys_ai_ready):
            self._emit_error("Moduły sprzętowe nie są gotowe do wznowienia.", recoverable=True)
            return
        self._game_controller.resume()
        self._change_state(SessionState.RUNNING)

    def finish_session(self):
        if self._state in (SessionState.RUNNING, SessionState.PAUSED):
            self._game_controller.end(GameEndReason.ABORTED)
            self._change_state(SessionState.FINISHED)

    def reset_session(self):
        if self._state == SessionState.RUNNING:
            raise InvalidStateTransitionError("Nie można zresetować sesji w trakcie RUNNING.")
        self._game_controller.reset()
        self.session_id = None
        self.game_id = ""
        self._difficulty_profile = None
        self._player_camera_mapping = {}
        self._selected_algorithms = {}
        self._sys_camera_ready = False
        self._sys_ai_ready = False
        self._state = SessionState.IDLE

    @Slot(CameraStatusEvent)
    def handle_camera_status(self, event: CameraStatusEvent):
        self._sys_camera_ready = event.current_state == CameraState.STREAMING
        if self._state == SessionState.RUNNING:
            if event.current_state == CameraState.DISCONNECTED:
                self._change_state(SessionState.ERROR)
                self._emit_error("Kamera rozłączona podczas gry!", recoverable=True)
            elif event.current_state == CameraState.ERROR:
                self.pause_session()
                self._emit_error("Błąd kamery podczas gry - sesja wstrzymana.", recoverable=True)
        self._check_auto_start()

    @Slot(InferenceStatusEvent)
    def handle_inference_status(self, event: InferenceStatusEvent):
        self._sys_ai_ready = event.current_state == InferenceState.READY
        self._check_auto_start()

    @Slot(GestureRecognitionEvent)
    def handle_gesture_event(self, event: GestureRecognitionEvent):
        if self._state != SessionState.RUNNING:
            return
        self._game_controller.handle_gesture(event)
        self._push_expected_signs()

    def _emit_error(self, message: str, recoverable=False):
        self.error_occurred.emit(
            ApplicationErrorEvent(
                source=SourceType.SESSION,
                severity=Severity.ERROR,
                code="SES_ERR",
                message=message,
                recoverable=recoverable,
            )
        )
