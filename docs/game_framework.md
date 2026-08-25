# Minigame Framework

This document describes the common framework every HandGame 2.0 minigame is built
against: `BaseGame`, the supporting models (`GameContext`, `DifficultyProfile`,
`PlayerGameState`, `GameResult`), and `GameController`, the Qt boundary that owns
the active game and talks to `SessionManager`.

Source: `src/handgame/games/`.

## Design principle

A minigame is pure Python domain logic. It never touches Qt, the camera, the AI
model, or the GUI directly. It receives typed inputs (`GameContext` at start,
`GestureRecognitionEvent` per gesture) and reports outcomes through a small
callback interface (`GameEventSink`). Everything Qt-shaped - signals consumed by
`SessionManager`, threading, event delivery - lives one layer up, in
`GameController`.

This split is what makes `tests/test_base_game.py` pure-Python unit tests: no
`qtbot`, no event loop, no camera, no AI model required.

## `BaseGame`

`games/base_game.py`. Abstract base class (`ABC`, not `QObject`).

```python
class BaseGame(ABC):
    def __init__(self, event_sink: GameEventSink) -> None: ...

    # Required - implemented by every minigame
    def start(self, context: GameContext) -> None: ...
    def update_frame(self, delta_ms: float) -> None: ...
    def end(self, reason: GameEndReason = GameEndReason.COMPLETED) -> GameResult: ...
    def _on_gesture(self, event: GestureRecognitionEvent) -> None: ...  # abstract hook

    # Provided - do not override
    def handle_gesture(self, event: GestureRecognitionEvent) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def reset(self) -> None: ...
    def use_hint(self, player_id: PlayerId) -> None: ...
    def get_state(self) -> GameState: ...
    def get_result(self) -> GameResult | None: ...
    def get_expected_sign(self, player_id: PlayerId) -> str | None: ...
    def get_player_state(self, player_id: PlayerId) -> PlayerGameState: ...
```

### `handle_gesture` is a template method, not abstract

The spec that seeded this framework listed `handle_gesture` as one of the
methods every minigame implements from scratch. In practice that means every
minigame re-implements the same three guard checks (state must be RUNNING,
event must belong to the current session, event must come from a known
player/camera). This framework centralizes that filtering in `BaseGame.handle_gesture`
and gives minigames a narrower abstract hook instead:

```python
def _on_gesture(self, event: GestureRecognitionEvent) -> None:
    """Called only after handle_gesture() has confirmed the event is valid."""
```

`handle_gesture` rejects (and reports via `GameEventSink.on_error`) an event if:

- the game is not `RUNNING`,
- `event.session_id` does not match the active `GameContext.session_id`,
- `event.player_id` is not one of the context's players,
- `event.camera_id` does not match the camera assigned to that player.

A minigame's `_on_gesture` can assume all of the above already holds.

### State machine

```
CREATED --> READY --> RUNNING <--> PAUSED --> FINISHED
   |          |           |           |           
   +--------- ERROR <-----+-----------+
```

Enforced centrally by `BaseGame._transition()`. Any transition not in the table
is rejected (logged + reported via `on_error`, state unchanged) rather than
raising - a stray `pause()` call from the GUI should never crash a game.
`reset()` is the one unconditional escape hatch: it can be called from any
state and always returns to `CREATED`, ready for the next session (this is
what demo mode relies on between rounds).

### Helper methods for subclasses

`BaseGame` provides three protected helpers so subclasses don't hand-roll
state bookkeeping:

- `_begin(context)` - `CREATED -> READY`, stores the context, builds a fresh
  `PlayerGameState` per player in `context.player_camera_mapping`.
- `_enter_running()` - `READY -> RUNNING`.
- `_update_player(player_id, **changes)` - builds a new `PlayerGameState` via
  `dataclasses.replace()` (they're frozen), stores it, and fires
  `on_score_changed`.
- `_finalize(reason)` - builds the `GameResult` (idempotent - calling it twice
  returns the same cached result), transitions to `FINISHED`/`ERROR`, and
  fires `on_finished`. Every minigame's `end()` should just call this.

### `GameEventSink`

A `typing.Protocol`, not a base class - any object with these six methods
satisfies it. `GameController` implements it directly (see below).

```python
class GameEventSink(Protocol):
    def on_state_changed(self, state: GameState) -> None: ...
    def on_score_changed(self, player_state: PlayerGameState) -> None: ...
    def on_hint_requested(self, player_id: PlayerId, hint: str) -> None: ...
    def on_action_ready(self, action: GameActionEvent) -> None: ...
    def on_finished(self, result: GameResult) -> None: ...
    def on_error(self, message: str, recoverable: bool) -> None: ...
```

## Models

`games/game_context.py`:

| Type | Fields | Notes |
|---|---|---|
| `DifficultyProfile` | `level` (1-5), `gesture_timeout_ms`, `hint_delay_ms`, `hint_duration_ms`, `sequence_length`, `board_size`, `allowed_mistakes`, `speed_multiplier=1.0`, `metadata` | Frozen dataclass. Rejects `level` outside 1-5 and negative timing/count fields. |
| `PlayerGameState` | `player_id`, `score=0`, `mistakes=0`, `hint_count=0`, `current_step=0`, `is_active=True` | Frozen dataclass - updated via `dataclasses.replace()`, never mutated in place. |
| `GameContext` | `session_id`, `game_id`, `mode: GameMode`, `difficulty: DifficultyProfile`, `player_camera_mapping: Mapping[PlayerId, CameraId]`, `selected_algorithms: Mapping[CameraId, str]`, `config` | Everything a minigame needs to start. Mappings are frozen (`MappingProxyType`) after construction. |

`build_difficulty_profile(level: int) -> DifficultyProfile` returns a preset
for levels 1-5. **The numbers in `DIFFICULTY_PRESETS` are placeholders** -
they were picked to be internally consistent (harder = shorter timeouts,
fewer allowed mistakes, faster pace) but have not been playtested. Tune them
before shipping.

`games/game_result.py`:

| Type | Fields | Notes |
|---|---|---|
| `GameEndReason` | `COMPLETED`, `TIMEOUT`, `ABORTED`, `ERROR` | Only `ERROR` maps to `GameResult.final_state == GameState.ERROR`; the other three all mean the game genuinely finished (`GameState.FINISHED`), just for different reasons. |
| `GameResult` | `session_id`, `game_id`, `final_state: GameState`, `end_reason: GameEndReason`, `player_results: Mapping[PlayerId, PlayerGameState]`, `started_at`, `finished_at`, `duration_ms`, `metadata` | Frozen, `duration_ms` validated non-negative. This is what `StatsSink.record_result()` consumes. |

`GameState` and `GameMode` live in `core/models.py` alongside the other
system-state enums (`CameraState`, `InferenceState`, `SessionState`) rather
than under `games/` - they're the same kind of thing (a state vocabulary
shared across the app) and `SessionManager`/`GameContext` both need to
reference `GameMode` without a `session -> games -> core` import chain.

## `GameController`

`games/game_controller.py`. A `QObject` - this is where Qt starts. It is the
**only** thing that constructs, drives, and destroys `BaseGame` instances.

- Owns a small registry: `GAME_REGISTRY: dict[str, type[BaseGame]]`. Adding a
  new minigame is one line here.
- Implements `GameEventSink` directly (structurally - no inheritance needed,
  it's a `Protocol`), translating each callback into a Qt signal:
  `game_action_ready`, `metrics_ready`, `game_finished`, `game_error`,
  `game_state_changed`, `score_changed`, `hint_requested` - all `Signal(object)`.
- `handle_gesture(event)` delegates to the active game, then builds the
  per-gesture `SessionMetricsEvent` itself (reading the player's score/
  mistakes/hint_count off the just-updated `PlayerGameState`, and
  `event.latency_ms` as the reaction time). This is deliberately **not**
  inside `BaseGame` - "emit a metrics snapshot after every gesture" is a
  session-level concern common to every minigame, not something each
  minigame should reimplement.
- `create_game(game_id, context)` looks the id up in `GAME_REGISTRY` and
  raises `KeyError` on an unknown id (caught by `SessionManager`, reported as
  an `ApplicationErrorEvent`, session stays out of `RUNNING`).

`SessionManager` owns exactly one `GameController` for its whole lifetime and
connects its signals straight through to matching `SessionManager` signals -
see `docs/gui_camera_ai_contract.md` for the full wiring.

## Implementing a new minigame

Use `games/example_gesture_game.py` as the template. Steps:

1. Create `games/<your_game>.py` with a class `class YourGame(BaseGame):`.
2. Give it a `GAME_ID: ClassVar[str]` and register it in
   `game_controller.GAME_REGISTRY`.
3. Implement `start(context)`: call `self._begin(context)`, then read
   `context.difficulty` and `context.player_camera_mapping` to set up
   whatever per-player state your game needs, then call
   `self._enter_running()`.
4. Implement `update_frame(delta_ms)`: only needed if your game has
   time-based behavior (countdown timers, delayed hints). Called
   periodically by whoever drives the game loop - never call
   `time.sleep()` or spin your own `QTimer` here, `BaseGame` must stay
   framework-agnostic.
5. Implement `_on_gesture(event)`: your actual game logic. Use
   `self._update_player(player_id, **changes)` to record score/mistakes -
   never mutate a `PlayerGameState` in place, it's frozen. Call
   `self._sink.on_action_ready(GameActionEvent(...))` for anything the GUI
   or stats should see per gesture.
6. Implement `end(reason)`: `return self._finalize(reason)`. That's usually
   the entire method body.
7. Optionally override `get_expected_sign(player_id)` if your game has a
   well-defined "next expected sign" concept - `SessionManager` reads this
   after every state change and forwards it to `InferenceManager` so the AI
   worker knows what to look for next.
8. Write `tests/test_<your_game>.py` following `tests/test_base_game.py`'s
   pattern: construct the game directly with a recording `GameEventSink`
   stub, no Qt required.

## What a minigame cannot do

- Read from or control the camera. It never sees a `FramePacket`.
- Run AI inference, or import anything from `recognition/`.
- Create a `QThread` or a `QTimer` of its own.
- Import `QtWidgets`, or anything from `gui/`.
- Write to `StatsSink` directly. It only returns `GameResult` /
  emits `GameActionEvent` through `GameEventSink`; `GameController` and
  `SessionManager` are responsible for getting that data to `StatsSink`.
- Implement rules specific to another minigame's genre inside `BaseGame`
  itself - genre-specific logic (Puzzle, Memory, Guitar-Hero-style timing,
  etc.) belongs entirely in the subclass, never in the shared base.
