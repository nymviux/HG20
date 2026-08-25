# GUI <-> Camera <-> AI <-> Session <-> Minigame <-> Stats Contract

This document is the source of truth for how the pieces of HandGame 2.0 talk
to each other: what events exist, what each component's states mean, the
threading rules every worker must follow, and the startup/shutdown lifecycle.
Read this before touching `camera/`, `recognition/`, `session/`, `games/`,
`stats/`, or `gui/integration_controller.py`.

## Component map

```
GUI (widgets)
  -> GUIIntegrationController          (facade; no QtWidgets import)
       -> CameraManager                (owns CameraWorkerHandle + QThread per camera)
            -> MockCameraWorker / BaseCameraWorker   (runs inside its QThread)
       -> InferenceManager             (owns InferenceWorkerHandle + QThread per camera)
            -> MockInferenceWorker / BaseInferenceWorker  (runs inside its QThread)
       -> SessionManager               (session state machine)
            -> GameController          (owns the active BaseGame instance)
                 -> BaseGame subclass  (pure Python, no Qt)
       -> StatsSink                    (in-memory now, SQLite-ready seam)
```

`GUIIntegrationController` is the only object the GUI layer talks to.
`SessionManager` never references `CameraManager`/`InferenceManager` directly
- it only exposes slots (`handle_camera_status`, `handle_inference_status`,
`handle_gesture_event`) that the controller wires up. This keeps
`SessionManager` fully testable without any camera/AI machinery running.

## Events (`core/events.py`)

All frozen dataclasses. One file - do not add a competing event type
elsewhere.

| Event | Key fields | Notes |
|---|---|---|
| `FramePacket` | `camera_id`, `frame_id`, `frame`, `player_id?`, `timestamp` | `frame` is a transient in-memory object (e.g. `np.ndarray`). **Never** persisted - not to `StatsSink`, not to logs, not to SQLite. |
| `GestureRecognitionEvent` | `session_id`, `player_id`, `camera_id`, `algorithm_id`, `expected_sign?`, `recognized_sign?`, `confidence?`, `is_correct?`, `latency_ms?` | `confidence` in `[0, 1]`; `latency_ms >= 0`; `expected_sign`/`recognized_sign`, if given, cannot be `""`. |
| `CameraStatusEvent` | `camera_id`, `previous_state`, `current_state`, `player_id?`, `message?` | |
| `InferenceStatusEvent` | `algorithm_id`, `previous_state`, `current_state`, `camera_id?`, `message?` | |
| `SessionStatusEvent` | `session_id`, `previous_state`, `current_state`, `message?` | |
| `ApplicationErrorEvent` | `source: SourceType`, `severity: Severity`, `code`, `message`, `recoverable`, `camera_id?`, `player_id?`, `exception_type?` | The one uniform error channel every manager funnels into. |
| `GameActionEvent` | `session_id`, `player_id`, `action_type`, `payload`, `timestamp` | `payload` is frozen (`MappingProxyType`) in `__post_init__` - construct it once, never mutate after. |
| `SessionMetricsEvent` | `session_id`, `game_id`, `difficulty_level` (1-5), `player_id?`, `score?`, `mistakes?`, `hint_count?`, `reaction_time_ms?` | Never carries frame/image data - it structurally can't. |

## States

- `CameraState`: `DISCONNECTED -> CONNECTING -> READY -> STREAMING -> ERROR / STOPPING`
- `InferenceState`: `IDLE -> STARTING -> READY -> PROCESSING -> ERROR / STOPPING`
- `SessionState`: `IDLE -> PREPARING -> RUNNING <-> PAUSED -> FINISHED / ERROR`
- `GameState`: see `docs/game_framework.md` (`CREATED -> READY -> RUNNING <-> PAUSED -> FINISHED / ERROR`)

`SessionState.RUNNING` is only reachable once both the required camera(s) are
`STREAMING` and the required inference worker(s) are `READY`
(`SessionManager._check_auto_start`).

## Signal typing convention

**Every cross-object `Signal` in this codebase carries `object`, and every
receiving slot is `@Slot(object)`.** The concrete payload type is documented
next to the `Signal(object)` declaration (as a comment) and enforced by
tests, not by the Qt meta-object system.

This applies uniformly at the worker level (`BaseCameraWorker`,
`BaseInferenceWorker`) and the manager/controller level
(`CameraManager`, `InferenceManager`, `GameController`, `SessionManager`,
`GUIIntegrationController`). Earlier revisions of this codebase mixed
strongly-typed `Signal(SomeDataclass)` at the worker level with `Signal(object)`
at the manager level; that inconsistency has been removed. Passing a Python
object through a `Signal(object)` connection works identically to a typed
signal at runtime (Qt only checks parameter count/compatibility for queued
delivery) - the only thing given up is compile-time Qt-side type checking,
which nothing else in this codebase relied on either.

**Never** use `QMetaObject.invokeMethod(worker, "some_slot", ...)` with a
string slot name to reach across threads. Use a `*Handle` proxy object (see
below) with real `Signal`/`Slot` connections instead - it's just as safe
cross-thread and gives you static analysis and refactor-safety that a string
literal doesn't.

## Thread safety rules

1. One `QThread` per camera, one `QThread` per AI worker (per camera). The
   main/GUI thread never reads a camera, never runs inference, never blocks
   on I/O.
2. A worker is a `QObject` moved via `moveToThread()` - never a `QThread`
   subclass carrying business logic.
3. **Do not parent a `QThread` to its owning manager** (`QThread(self)`).
   Ownership must be exactly one mechanism, not two: `worker.finished ->
   thread.quit()` / `thread.finished -> thread.deleteLater()` already fully
   owns the thread's lifecycle. Parenting it to `self` *as well* creates a
   double-ownership race - if the manager itself is destroyed (e.g. via
   Python's GC) before the thread has processed its own queued
   `deleteLater()`, the C++ parent-child cascade deletes the thread
   synchronously on the wrong thread while a stale `deleteLater()` event for
   the *same* object is still sitting in the main thread's queue. The next
   `processEvents()` call then dispatches that stale event against an
   already-freed object - a real, reproducible segfault, not a theoretical
   one (see the fix in `camera_manager.py` / `inference_manager.py`:
   `thread = QThread()`, no parent).
4. All requests from a manager *into* a worker's thread go through a `*Handle`
   proxy object (`CameraWorkerHandle`, `InferenceWorkerHandle`) that lives in
   the manager's thread, with every connection to the worker made with
   explicit `Qt.ConnectionType.QueuedConnection`. Never call
   `worker.stop_stream()`, `worker.submit_frame()`, etc. directly from the
   manager - always go through the handle's signals.
5. Every `QTimer` a worker owns (e.g. `MockCameraWorker`'s frame-emission
   timer) must be created, started, and stopped from inside that worker's
   own thread - i.e. from within a slot that only ever runs after
   `moveToThread()`, never from `__init__`.
6. `worker.finished` triggers, in this order: `thread.quit()`, then
   `worker.deleteLater()`. `thread.finished` triggers `thread.deleteLater()`.
   A worker's `stop_*()` slot must stop its own `QTimer` *before* emitting
   `finished` - never emit `finished` while a timer could still fire.

## Latest-frame-wins

`InferenceManager.process_frame()` (the pattern every future per-camera
worker manager should copy) never queues frames. It tracks one `_is_busy`
flag per camera:

```python
if self._states.get(camera_id) != InferenceState.READY:
    return
if self._is_busy.get(camera_id, False):
    return
self._is_busy[camera_id] = True
runtime.handle.frame_requested.emit(packet)
```

A frame arriving while the previous one is still being processed is silently
dropped - there is no buffer, no backlog, ever. `_is_busy` is cleared on
`gesture_recognized`, on a worker error, and when status transitions to
`ERROR`, so a stuck-busy state can never permanently block new frames.

## Lifecycle: start / stop / shutdown

`CameraManager`/`InferenceManager` both follow the identical shape:

- `start_camera()` / `start_algorithm()`: build worker + `QThread` (unparented,
  see rule 3 above) + `*Handle`, wire everything with `QueuedConnection`,
  `thread.start()`. The runtime (`thread`, `worker`, `handle`) is stored in a
  single dict keyed by `CameraId`, never split across multiple dicts.
- `stop_camera()` / `stop_algorithm()`: idempotent (checks the current state
  is not already `STOPPING` before acting), emits `handle.stop_requested`.
  **Never** mutates the runtime dict here - only the request is sent.
- `_cleanup_runtime()`: the *only* place that pops the runtime dict entry.
  Connected to `thread.finished`, so it only ever runs once the `QThread` has
  genuinely stopped.
- `shutdown(timeout_ms=3000)`: stops everything, then waits for each thread
  via `wait_for_thread_stopped()` (`core/qt_utils.py`) - **not** a bare
  `thread.wait(timeout_ms)`. A bare `wait()` blocks the calling thread
  without pumping its own event loop, which means the queued
  `worker.finished -> thread.quit()` call (a cross-thread `QueuedConnection`)
  can never be delivered while `wait()` is blocking - every `shutdown()`
  would silently eat the *entire* timeout on every call, every time, even
  though the worker actually finished in milliseconds. `wait_for_thread_stopped()`
  alternates `QCoreApplication.processEvents()` with short polls so the
  queued call actually gets a chance to run, and returns as soon as the
  thread is genuinely done. If a thread still hasn't stopped after the full
  timeout, the fallback calls `thread.quit()` directly (bypassing the queue)
  and does one more short `wait()` - `thread.terminate()` is never used.
  Finally, a sweep pops any runtime whose thread is confirmed not running,
  covering the case where a test has no running Qt event loop pumping
  `thread.finished` on its own.
- `shutdown()` is idempotent: calling it twice (or calling `stop_camera()`
  twice) must never raise, warn, or hang. Both managers' `stop_*()` methods
  guard on current state; `shutdown()`'s loops simply no-op over an empty
  runtime dict on a second call.

`GUIIntegrationController.shutdown()` calls, in order:
`session_mgr.finish_session()` -> `camera_mgr.shutdown()` ->
`inference_mgr.shutdown()`. Tests must always call this in a `finally` block
or fixture teardown (see `tests/conftest.py`'s `controller` fixture).

## Full data flow

1. GUI calls `GUIIntegrationController.select_camera(camera_id, player_id)`
   and `select_algorithm(camera_id, algorithm_id)` (or the default
   `select_camera` auto-starts `"MOCK_YOLO"`) - these also register the
   player<->camera and camera<->algorithm mappings on `SessionManager`.
2. GUI calls `prepare_game(game_id, difficulty, mode)`.
   `SessionManager.prepare_session()` creates `session_id`, stores
   `game_id`/`mode`, builds a `DifficultyProfile` via
   `build_difficulty_profile(difficulty)`, transitions to `PREPARING`.
3. `CameraManager.start_camera()` / `InferenceManager.start_algorithm()` spin
   up their workers (steps 1-2 usually trigger this already).
4. Camera worker emits `CameraStatusEvent` (`CONNECTING -> READY -> STREAMING`).
5. AI worker emits `InferenceStatusEvent` (`STARTING -> READY`).
6. Once both `_sys_camera_ready` and `_sys_ai_ready` are true,
   `SessionManager` builds a `GameContext` and calls
   `GameController.create_game(game_id, context)`, which looks the game up
   in `GAME_REGISTRY`, instantiates it, and calls `BaseGame.start(context)`.
   Only then does `SessionManager` transition to `RUNNING`.
7. `SessionManager._push_expected_signs()` reads each player's current
   `get_expected_sign()` from the game and forwards it through
   `expected_sign_ready` -> `GUIIntegrationController` ->
   `InferenceManager.set_expected_sign(...)`, so the AI worker knows what
   sign each player's camera should be looking for next.
8. `CameraWorker` emits `FramePacket` -> `CameraManager.frame_ready` ->
   `InferenceManager.process_frame()` (latest-frame-wins, see above).
9. `InferenceWorker` emits `GestureRecognitionEvent` ->
   `InferenceManager.gesture_recognized` -> `SessionManager.handle_gesture_event()`.
10. `SessionManager` delegates to `GameController.handle_gesture()`, which
    delegates to `BaseGame.handle_gesture()` (filters + `_on_gesture` hook),
    then builds and emits a `SessionMetricsEvent`.
11. The minigame emits `GameActionEvent` (correct/incorrect gesture, score
    change, etc.) via `GameEventSink.on_action_ready` -> `GameController` ->
    `SessionManager.game_action_ready` -> `GUIIntegrationController.ui_game_action`.
12. `SessionManager` re-pushes expected signs (step 7) for the next gesture.
13. `StatsSink.record_metrics()` / `record_gesture()` save only the fields
    listed in the events table above - no frame data, ever.
14. When the minigame's sequence completes, it calls `self.end(...)`,
    producing a `GameResult`, which flows through `GameController.game_finished`
    -> `SessionManager.game_finished` -> `GUIIntegrationController.ui_game_finished`
    and `StatsSink.record_result()`.
15. `GUIIntegrationController.shutdown()` (wired to `app.aboutToQuit`, and
    called explicitly by tests) stops games, cameras, and AI workers with no
    orphaned `QThread`s left behind.

## Error handling

Every manager funnels its errors into a single `ApplicationErrorEvent` and
its own `error_occurred` signal. `GUIIntegrationController` fans all of them
out to `ui_error_occurred` (for the GUI to show a message) and
`EventBus.global_error` (diagnostic/logging sink). Covered failure modes:

- Missing/disconnected camera mid-session -> `CameraState.DISCONNECTED` while
  `RUNNING` forces `SessionState.ERROR` (unrecoverable without a reset).
- Recoverable camera fault -> `CameraState.ERROR` while `RUNNING` pauses the
  session (`SessionState.PAUSED`) instead of hard-failing it, since the
  underlying worker stays alive and can recover.
- Frame read / inference error -> the mock workers' `force_error()` /
  `configure_mock_result(is_error=True)` hooks simulate this in tests;
  real workers should emit `ApplicationErrorEvent(source=SourceType.CAMERA
  or INFERENCE, recoverable=...)` the same way.
- No gesture recognized -> `GestureRecognitionEvent.recognized_sign` can be
  `None` (never `""`); a minigame's `_on_gesture` should treat that as "no
  match" the same as any other wrong answer.
- Start attempted before camera/AI ready -> `SessionManager.start_session()`
  no-ops and emits a recoverable error instead of transitioning.
- Invalid state transition -> `SessionManager.prepare_session()` raises
  `InvalidStateTransitionError`; `BaseGame._transition()` logs + reports via
  `on_error` without raising (a stray GUI click must never crash a game).
- Unknown `game_id` -> `GameController.create_game()` raises `KeyError`,
  caught by `SessionManager.start_session()`, reported as an error, session
  stays in `PREPARING`.

## APIs that must not change without consulting the GUI lead

- `GUIIntegrationController`'s public method signatures: `select_camera`,
  `select_algorithm`, `prepare_game`, `start_game`, `pause_game`,
  `resume_game`, `finish_game`, `reset_game`, `shutdown`.
- All `ui_*` signals on `GUIIntegrationController`: `ui_camera_status_changed`,
  `ui_session_status_changed`, `ui_inference_status_changed`,
  `ui_gesture_result`, `ui_game_action`, `ui_game_finished`,
  `ui_error_occurred`.
- The event dataclasses in `core/events.py` and the state enums in
  `core/models.py` - these are the shared vocabulary every team (camera, AI,
  minigame, GUI) codes against.

## Instructions per team

- **Camera team**: implement `BaseCameraWorker` for real hardware. You must
  provide `start_stream`/`stop_stream`/`restart_stream` as `@Slot()` methods
  that only ever run inside the worker's own thread (post-`moveToThread`),
  emit `frame_captured`/`status_changed`/`error_occurred` as `Signal(object)`,
  and never build an unbounded frame buffer - if `CameraManager` can't keep
  up, drop frames, don't queue them.
- **AI team**: implement `BaseInferenceWorker.start`/`submit_frame`. Real
  inference will likely block for real time inside `submit_frame` - that's
  fine, it runs in its own thread, but it must never call back into the GUI
  thread synchronously, and must respect `stop()` being requested mid-inference
  (check a cancellation flag between blocking chunks if the model API allows it).
- **Minigame team**: read `docs/game_framework.md`. You only ever touch
  `games/`, never `camera/`, `recognition/`, `gui/`.
- **GUI team**: only ever call methods on `GUIIntegrationController` and
  connect to its `ui_*` signals, in the main thread. Never reach into
  `camera_mgr`/`inference_mgr`/`session_mgr` directly.
