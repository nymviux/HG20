import pytest

from handgame.core.errors import InvalidStateTransitionError
from handgame.core.events import CameraStatusEvent, GestureRecognitionEvent, InferenceStatusEvent
from handgame.core.models import CameraId, CameraState, InferenceState, PlayerId, SessionState
from handgame.games.example_gesture_game import ExampleGestureGame
from handgame.session.session_manager import SessionManager


def test_legal_and_illegal_transitions(qapp):
    mgr = SessionManager()

    # Legalne
    mgr.prepare_session("TEST", 1)
    assert mgr._state == SessionState.PREPARING

    # Nielegalne
    with pytest.raises(InvalidStateTransitionError):
        mgr.prepare_session("TEST2", 2)


def _make_ready_session(mgr: SessionManager) -> None:
    mgr.register_camera_mapping(CameraId.CAMERA_1, PlayerId.PLAYER_1)
    mgr.register_algorithm_mapping(CameraId.CAMERA_1, "MOCK_YOLO")
    mgr.prepare_session(ExampleGestureGame.GAME_ID, 1)
    mgr.handle_camera_status(
        CameraStatusEvent(CameraId.CAMERA_1, CameraState.CONNECTING, CameraState.STREAMING)
    )
    mgr.handle_inference_status(
        InferenceStatusEvent("MOCK_YOLO", InferenceState.STARTING, InferenceState.READY)
    )


def test_session_auto_starts_once_camera_and_ai_ready(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)
    assert mgr._state == SessionState.RUNNING


def test_start_session_blocked_without_camera_or_ai_ready(qapp):
    mgr = SessionManager()
    mgr.register_camera_mapping(CameraId.CAMERA_1, PlayerId.PLAYER_1)
    mgr.register_algorithm_mapping(CameraId.CAMERA_1, "MOCK_YOLO")
    mgr.prepare_session(ExampleGestureGame.GAME_ID, 1)

    mgr.start_session()

    assert mgr._state == SessionState.PREPARING


def test_pause_resume_round_trip(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    mgr.pause_session()
    assert mgr._state == SessionState.PAUSED

    mgr.resume_session()
    assert mgr._state == SessionState.RUNNING


def test_finish_session_and_reset(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    mgr.finish_session()
    assert mgr._state == SessionState.FINISHED

    mgr.reset_session()
    assert mgr._state == SessionState.IDLE
    assert mgr.session_id is None


def test_reset_session_rejected_while_running(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    with pytest.raises(InvalidStateTransitionError):
        mgr.reset_session()


def test_handle_gesture_event_delegates_to_game_controller(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    actions = []
    mgr.game_action_ready.connect(actions.append)

    expected = mgr._game_controller._game.get_expected_sign(PlayerId.PLAYER_1)
    event = GestureRecognitionEvent(
        session_id=mgr.session_id,
        player_id=PlayerId.PLAYER_1,
        camera_id=CameraId.CAMERA_1,
        algorithm_id="MOCK_YOLO",
        recognized_sign=expected,
        confidence=0.9,
    )
    mgr.handle_gesture_event(event)

    assert len(actions) == 1
    assert actions[0].payload["is_correct"] is True


def test_camera_error_while_running_pauses_session(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    mgr.handle_camera_status(
        CameraStatusEvent(CameraId.CAMERA_1, CameraState.STREAMING, CameraState.ERROR)
    )

    assert mgr._state == SessionState.PAUSED


def test_camera_disconnect_while_running_errors_session(qapp):
    mgr = SessionManager()
    _make_ready_session(mgr)

    mgr.handle_camera_status(
        CameraStatusEvent(CameraId.CAMERA_1, CameraState.STREAMING, CameraState.DISCONNECTED)
    )

    assert mgr._state == SessionState.ERROR


def test_unknown_game_id_emits_error_and_stays_out_of_running(qapp):
    mgr = SessionManager()
    mgr.register_camera_mapping(CameraId.CAMERA_1, PlayerId.PLAYER_1)
    mgr.register_algorithm_mapping(CameraId.CAMERA_1, "MOCK_YOLO")
    errors = []
    mgr.error_occurred.connect(errors.append)

    mgr.prepare_session("NO_SUCH_GAME", 1)
    mgr.handle_camera_status(
        CameraStatusEvent(CameraId.CAMERA_1, CameraState.CONNECTING, CameraState.STREAMING)
    )
    mgr.handle_inference_status(
        InferenceStatusEvent("MOCK_YOLO", InferenceState.STARTING, InferenceState.READY)
    )

    assert mgr._state == SessionState.PREPARING
    assert len(errors) > 0
