"""Testy maszyny stanów BaseGame - przejścia legalne/nielegalne, reset()."""

from handgame.core.models import GameState
from handgame.games.example_gesture_game import ExampleGestureGame
from handgame.games.game_result import GameEndReason
from test_base_game import RecordingSink, make_context, make_gesture


def test_pause_before_start_is_rejected():
    sink = RecordingSink()
    game = ExampleGestureGame(sink)

    game.pause()

    assert game.get_state() == GameState.CREATED
    assert sink.errors


def test_resume_without_pause_is_rejected():
    sink = RecordingSink()
    game = ExampleGestureGame(sink)
    context = make_context()
    game.start(context)

    game.resume()

    assert game.get_state() == GameState.RUNNING
    assert sink.errors


def test_pause_resume_round_trip():
    sink = RecordingSink()
    game = ExampleGestureGame(sink)
    context = make_context()
    game.start(context)

    game.pause()
    assert game.get_state() == GameState.PAUSED

    game.resume()
    assert game.get_state() == GameState.RUNNING


def test_handle_gesture_after_end_is_rejected():
    sink = RecordingSink()
    game = ExampleGestureGame(sink)
    context = make_context()
    game.start(context)
    game.end(GameEndReason.ABORTED)

    assert game.get_state() == GameState.FINISHED
    errors_before = len(sink.errors)

    game.handle_gesture(make_gesture(context, "A"))

    assert len(sink.errors) == errors_before + 1


def test_reset_returns_to_created_from_any_state():
    sink = RecordingSink()
    game = ExampleGestureGame(sink)
    context = make_context()
    game.start(context)
    game.pause()

    game.reset()

    assert game.get_state() == GameState.CREATED
    assert game.get_result() is None
    assert game._context is None  # internal context cleared, ready for next session
