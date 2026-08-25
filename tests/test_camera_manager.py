"""Testy cyklu życia CameraManager - start/stop/restart, wątki, błędy."""

from handgame.camera.camera_manager import CameraManager
from handgame.core.models import CameraId, CameraState, PlayerId


def test_start_camera_reaches_streaming(qapp, qtbot):
    mgr = CameraManager()
    try:
        mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
        qtbot.waitUntil(
            lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
            timeout=3_000,
        )
    finally:
        mgr.shutdown()


def test_stop_camera_actually_stops_the_thread(qapp, qtbot):
    mgr = CameraManager()
    mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
    qtbot.waitUntil(
        lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
        timeout=3_000,
    )

    mgr.stop_camera(CameraId.CAMERA_1)
    # Once cleaned up, the QThread's underlying C++ object is gone (deleteLater()
    # already ran) - assert via the manager's own bookkeeping, not a held reference.
    qtbot.waitUntil(lambda: CameraId.CAMERA_1 not in mgr._runtimes, timeout=3_000)

    assert mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.DISCONNECTED


def test_double_stop_camera_is_idempotent(qapp, qtbot):
    mgr = CameraManager()
    try:
        mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
        qtbot.waitUntil(
            lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
            timeout=3_000,
        )
        mgr.stop_camera(CameraId.CAMERA_1)
        mgr.stop_camera(CameraId.CAMERA_1)  # must not raise / duplicate-stop
    finally:
        mgr.shutdown()


def test_restart_camera(qapp, qtbot):
    mgr = CameraManager()
    try:
        mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
        qtbot.waitUntil(
            lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
            timeout=3_000,
        )
        mgr.restart_camera(CameraId.CAMERA_1)
        qtbot.waitUntil(
            lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
            timeout=3_000,
        )
    finally:
        mgr.shutdown()


def test_force_camera_error_emits_application_error_event(qapp, qtbot):
    mgr = CameraManager()
    errors = []
    mgr.error_occurred.connect(errors.append)
    try:
        mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
        qtbot.waitUntil(
            lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING,
            timeout=3_000,
        )
        mgr.force_camera_error(CameraId.CAMERA_1, "boom")
        qtbot.waitUntil(lambda: len(errors) > 0, timeout=3_000)
        assert errors[0].message == "boom"
        assert mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.ERROR
    finally:
        mgr.shutdown()


def test_shutdown_leaves_no_running_threads(qapp, qtbot):
    mgr = CameraManager()
    mgr.start_camera(CameraId.CAMERA_1, PlayerId.PLAYER_1)
    mgr.start_camera(CameraId.CAMERA_2, PlayerId.PLAYER_2)
    qtbot.waitUntil(
        lambda: mgr.get_camera_state(CameraId.CAMERA_1) == CameraState.STREAMING
        and mgr.get_camera_state(CameraId.CAMERA_2) == CameraState.STREAMING,
        timeout=3_000,
    )

    mgr.shutdown()

    assert len(mgr._runtimes) == 0
    # Double shutdown must be safe too.
    mgr.shutdown()
