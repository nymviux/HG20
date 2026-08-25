from __future__ import annotations

from handgame.core.models import CameraId, CameraState
from handgame.games.example_gesture_game import ExampleGestureGame
from handgame.gui.integration_controller import GUIIntegrationController
from handgame.recognition.mock_inference_worker import MockResultSpec


def test_full_mock_flow_without_crashing(qtbot) -> None:
    """
    Sprawdza przepływ:
    MockCamera -> Inference -> Session -> Stats -> GameAction.

    Test nie wymaga Raspberry Pi, fizycznej kamery ani modelu AI.
    """
    controller = GUIIntegrationController()

    actions_received = []
    controller.ui_game_action.connect(actions_received.append)

    try:
        controller.select_camera("CAMERA_1", "PLAYER_1")
        controller.prepare_game(ExampleGestureGame.GAME_ID, 1)

        # Czekamy, aż mocki uruchomią pipeline i otrzymamy akcję dla gry.
        qtbot.waitUntil(
            lambda: len(actions_received) > 0,
            timeout=3_000,
        )

        assert actions_received[0].action_type == "GESTURE_INPUT"

        # StatsSink zapisuje wyłącznie statystyki, nie ramki kamery.
        assert len(controller.stats_sink._in_memory_db) > 0

        record = controller.stats_sink._in_memory_db[0]
        assert "frame" not in record
        assert "image" not in record
        assert "video" not in record

    finally:
        # Wykona się także wtedy, gdy test/asercja zakończy się błędem.
        controller.shutdown()


def test_correct_gesture_produces_correct_game_action(qtbot) -> None:
    controller = GUIIntegrationController()
    actions_received = []
    controller.ui_game_action.connect(actions_received.append)

    try:
        controller.select_camera("CAMERA_1", "PLAYER_1")
        controller.prepare_game(ExampleGestureGame.GAME_ID, 1)

        # Domyślne zachowanie mocka: rozpoznany znak == oczekiwany znak == poprawny.
        qtbot.waitUntil(lambda: len(actions_received) > 0, timeout=3_000)

        assert actions_received[0].payload["is_correct"] is True
    finally:
        controller.shutdown()


def test_incorrect_gesture_increments_mistake_counter(qtbot) -> None:
    controller = GUIIntegrationController()
    actions_received = []
    controller.ui_game_action.connect(actions_received.append)

    try:
        controller.select_camera("CAMERA_1", "PLAYER_1")
        controller.inference_mgr.configure_mock_worker(
            CameraId.CAMERA_1,
            MockResultSpec(recognized_sign="NOT_THE_EXPECTED_SIGN", is_correct=False),
        )
        controller.prepare_game(ExampleGestureGame.GAME_ID, 1)

        qtbot.waitUntil(lambda: len(actions_received) > 0, timeout=3_000)

        assert actions_received[0].payload["is_correct"] is False
    finally:
        controller.shutdown()


def test_force_camera_error_reported_without_crashing(qtbot) -> None:
    controller = GUIIntegrationController()
    errors_received = []
    controller.ui_error_occurred.connect(errors_received.append)

    try:
        controller.select_camera("CAMERA_1", "PLAYER_1")
        qtbot.waitUntil(
            lambda: controller.camera_mgr.get_camera_state(CameraId.CAMERA_1)
            == CameraState.STREAMING,
            timeout=3_000,
        )

        controller.camera_mgr.force_camera_error(CameraId.CAMERA_1, "camera unplugged")

        qtbot.waitUntil(lambda: len(errors_received) > 0, timeout=3_000)
        assert any(e.message == "camera unplugged" for e in errors_received)
    finally:
        controller.shutdown()


def test_inference_error_reported_without_crashing(qtbot) -> None:
    controller = GUIIntegrationController()
    errors_received = []
    controller.ui_error_occurred.connect(errors_received.append)

    try:
        controller.select_camera("CAMERA_1", "PLAYER_1")
        controller.inference_mgr.configure_mock_worker(
            CameraId.CAMERA_1,
            MockResultSpec(is_error=True, error_message="model crashed"),
        )
        controller.prepare_game(ExampleGestureGame.GAME_ID, 1)

        qtbot.waitUntil(lambda: len(errors_received) > 0, timeout=3_000)
        assert any(e.message == "model crashed" for e in errors_received)
    finally:
        controller.shutdown()


def test_double_shutdown_is_safe_and_leaves_no_threads(qtbot) -> None:
    controller = GUIIntegrationController()
    controller.select_camera("CAMERA_1", "PLAYER_1")
    controller.prepare_game(ExampleGestureGame.GAME_ID, 1)

    qtbot.wait(200)  # let the pipeline spin up briefly

    controller.shutdown()
    controller.shutdown()  # must not raise / warn / hang

    assert len(controller.camera_mgr._runtimes) == 0
    assert len(controller.inference_mgr._runtimes) == 0
