from datetime import UTC, datetime
from uuid import uuid4

import pytest

from handgame.core.models import CameraId, GameMode, GameState, PlayerId
from handgame.games.game_context import DifficultyProfile, GameContext, build_difficulty_profile
from handgame.games.game_result import GameEndReason, GameResult


def test_difficulty_profile_rejects_out_of_range_level():
    with pytest.raises(ValueError, match="1-5"):
        DifficultyProfile(
            level=6,
            gesture_timeout_ms=1000,
            hint_delay_ms=500,
            hint_duration_ms=500,
            sequence_length=3,
            board_size=3,
            allowed_mistakes=2,
        )
    with pytest.raises(ValueError, match="1-5"):
        DifficultyProfile(
            level=0,
            gesture_timeout_ms=1000,
            hint_delay_ms=500,
            hint_duration_ms=500,
            sequence_length=3,
            board_size=3,
            allowed_mistakes=2,
        )


def test_difficulty_profile_rejects_negative_fields():
    with pytest.raises(ValueError):
        DifficultyProfile(
            level=1,
            gesture_timeout_ms=-1,
            hint_delay_ms=500,
            hint_duration_ms=500,
            sequence_length=3,
            board_size=3,
            allowed_mistakes=2,
        )


def test_build_difficulty_profile_covers_all_levels():
    for level in range(1, 6):
        profile = build_difficulty_profile(level)
        assert profile.level == level
    with pytest.raises(ValueError):
        build_difficulty_profile(99)


def test_game_context_freezes_mappings():
    context = GameContext(
        session_id=uuid4(),
        game_id="EXAMPLE_GESTURE_GAME",
        mode=GameMode.SINGLEPLAYER,
        difficulty=build_difficulty_profile(1),
        player_camera_mapping={PlayerId.PLAYER_1: CameraId.CAMERA_1},
        selected_algorithms={CameraId.CAMERA_1: "MOCK_YOLO"},
    )
    with pytest.raises(TypeError):
        context.player_camera_mapping[PlayerId.PLAYER_2] = CameraId.CAMERA_2


def test_game_result_rejects_negative_duration():
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        GameResult(
            session_id=uuid4(),
            game_id="EXAMPLE_GESTURE_GAME",
            final_state=GameState.FINISHED,
            end_reason=GameEndReason.COMPLETED,
            player_results={},
            started_at=now,
            finished_at=now,
            duration_ms=-1,
        )
