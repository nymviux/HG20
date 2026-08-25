from uuid import uuid4

import pytest

from handgame.core.events import GameActionEvent, GestureRecognitionEvent, SessionMetricsEvent
from handgame.core.models import CameraId, PlayerId


def test_gesture_event_validation():
    with pytest.raises(ValueError, match="Confidence musi"):
        GestureRecognitionEvent(
            uuid4(), PlayerId.PLAYER_1, CameraId.CAMERA_1, "ALG", confidence=1.5
        )

    with pytest.raises(ValueError, match="Latency nie może"):
        GestureRecognitionEvent(
            uuid4(), PlayerId.PLAYER_1, CameraId.CAMERA_1, "ALG", latency_ms=-10.0
        )

    with pytest.raises(ValueError, match="Recognized sign nie może"):
        GestureRecognitionEvent(
            uuid4(), PlayerId.PLAYER_1, CameraId.CAMERA_1, "ALG", recognized_sign=""
        )

    with pytest.raises(ValueError, match="Expected sign nie może"):
        GestureRecognitionEvent(
            uuid4(), PlayerId.PLAYER_1, CameraId.CAMERA_1, "ALG", expected_sign=""
        )


def test_metrics_event_validation():
    with pytest.raises(ValueError, match="Difficulty level"):
        SessionMetricsEvent(uuid4(), "GAME", 6)


def test_game_action_event_payload_is_immutable():
    action = GameActionEvent(
        session_id=uuid4(),
        player_id=PlayerId.PLAYER_1,
        action_type="GESTURE_INPUT",
        payload={"sign": "A"},
    )
    with pytest.raises(TypeError):
        action.payload["sign"] = "B"
