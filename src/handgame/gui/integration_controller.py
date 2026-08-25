import logging

from PySide6.QtCore import QObject, Signal, Slot

from handgame.camera.camera_manager import CameraManager
from handgame.core.event_bus import EventBus
from handgame.core.events import (
    ApplicationErrorEvent,
    CameraStatusEvent,
    GameActionEvent,
    SessionStatusEvent,
)
from handgame.core.models import CameraId, GameMode, PlayerId
from handgame.recognition.inference_manager import InferenceManager
from handgame.session.session_manager import SessionManager
from handgame.stats.stats_sink import StatsSink

logger = logging.getLogger(__name__)


class GUIIntegrationController(QObject):
    """
    Fasada dla GUI. Cały interfejs komunikuje się wyłącznie z tą klasą.
    NIE IMPORTUJE QtWidgets, więc może działać headless.
    """

    # Sygnały bezpieczne dla widoków (GUI subskrybuje te sygnały w głównym wątku)
    ui_camera_status_changed = Signal(CameraStatusEvent)
    ui_session_status_changed = Signal(SessionStatusEvent)
    ui_inference_status_changed = Signal(object)  # InferenceStatusEvent
    ui_gesture_result = Signal(object)  # GestureRecognitionEvent
    ui_game_action = Signal(GameActionEvent)
    ui_game_finished = Signal(object)  # GameResult
    ui_error_occurred = Signal(ApplicationErrorEvent)

    def __init__(self):
        super().__init__()
        self.event_bus = EventBus()

        self.camera_mgr = CameraManager()
        self.inference_mgr = InferenceManager()
        self.session_mgr = SessionManager()
        self.stats_sink = StatsSink()

        self._wire_connections()

    def _wire_connections(self):
        # Camera -> Inference
        self.camera_mgr.frame_ready.connect(self.inference_mgr.process_frame)

        # Inference -> Session & Stats
        self.inference_mgr.gesture_recognized.connect(self.session_mgr.handle_gesture_event)
        self.inference_mgr.gesture_recognized.connect(self.stats_sink.record_gesture)

        # Managers -> Session
        self.camera_mgr.camera_status_changed.connect(self.session_mgr.handle_camera_status)
        self.inference_mgr.inference_status_changed.connect(
            self.session_mgr.handle_inference_status
        )

        # Session -> Stats
        self.session_mgr.metrics_ready.connect(self.stats_sink.record_metrics)
        self.session_mgr.game_finished.connect(self.stats_sink.record_result)

        # Session -> Inference (kolejny oczekiwany znak dla gracza)
        self.session_mgr.expected_sign_ready.connect(self._on_expected_sign_ready)

        # Wystawienie sygnałów do GUI (GUI wyświetla stosowne komunikaty po otrzymaniu sygnału)
        self.camera_mgr.camera_status_changed.connect(self.ui_camera_status_changed)
        self.inference_mgr.inference_status_changed.connect(self.ui_inference_status_changed)
        self.inference_mgr.gesture_recognized.connect(self.ui_gesture_result)
        self.session_mgr.session_status_changed.connect(self.ui_session_status_changed)
        self.session_mgr.game_action_ready.connect(self.ui_game_action)
        self.session_mgr.game_finished.connect(self.ui_game_finished)

        # Agregacja błędów (GUI powinno pokazać QMessageBox po otrzymaniu)
        for mgr in (self.camera_mgr, self.inference_mgr, self.session_mgr):
            mgr.error_occurred.connect(self.ui_error_occurred)
            mgr.error_occurred.connect(self.event_bus.global_error)

    @Slot(object)
    def _on_expected_sign_ready(self, payload: tuple) -> None:
        session_id, player_id, camera_id, expected_sign = payload
        self.inference_mgr.set_expected_sign(
            str(session_id), player_id.name, expected_sign or "", camera_id
        )

    # --- API DLA WIDOKÓW GUI ---

    @Slot(str, int)
    @Slot(str, int, str)
    def prepare_game(self, game_id: str, difficulty: int, mode: str = "SINGLEPLAYER"):
        """Wywoływane przez wciśnięcie przycisku 'Start' w widoku menu."""
        self.session_mgr.prepare_session(game_id, difficulty, GameMode[mode])

    @Slot(str, str)
    def select_camera(self, camera_id_str: str, player_id_str: str):
        cam = CameraId[camera_id_str]
        player = PlayerId[player_id_str]
        self.session_mgr.register_camera_mapping(cam, player)
        self.session_mgr.register_algorithm_mapping(cam, "MOCK_YOLO")
        self.camera_mgr.start_camera(cam, player)
        self.inference_mgr.start_algorithm(cam, "MOCK_YOLO")

    @Slot(str, str)
    def select_algorithm(self, camera_id_str: str, algorithm_id: str):
        cam = CameraId[camera_id_str]
        if self.inference_mgr.is_algorithm_running(cam):
            # Zatrzymanie jest asynchroniczne (patrz InferenceManager.stop_algorithm) -
            # nowy algorytm trzeba wybrać ponownie po zaobserwowaniu IDLE.
            logger.warning(
                "select_algorithm: %s already running for %s, stopping it first.",
                cam,
                camera_id_str,
            )
            self.inference_mgr.stop_algorithm(cam)
            return
        self.inference_mgr.start_algorithm(cam, algorithm_id)
        self.session_mgr.register_algorithm_mapping(cam, algorithm_id)

    @Slot()
    def start_game(self):
        self.session_mgr.start_session()

    @Slot()
    def pause_game(self):
        self.session_mgr.pause_session()

    @Slot()
    def resume_game(self):
        self.session_mgr.resume_session()

    @Slot()
    def finish_game(self):
        self.session_mgr.finish_session()

    @Slot()
    def reset_game(self):
        self.session_mgr.reset_session()

    @Slot()
    def shutdown(self):
        """Wywoływane przez app.aboutToQuit"""
        logger.info("GUI Controller initiating shutdown...")
        self.session_mgr.finish_session()
        self.camera_mgr.shutdown()
        self.inference_mgr.shutdown()
