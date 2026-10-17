"""The automation engine (no GUI, no Windows-specific code).

Behaviour
---------
* Runs the *enabled* keys in order (F1 -> F10).  After each key it waits that
  key's own delay, then moves on to the next one.  When the last key's delay
  is over the sequence starts again, until stop() is called.
* In tap mode, a key-down is followed immediately by key-up. The per-key delay
  controls the wait before the next key; hold mode keeps the key down.
* Every wait is done on a threading.Event, so stop() interrupts a delay or
  a held key *immediately* instead of waiting for it to finish.
* stop() releases any key that is still down, synchronously, from the
  calling thread; the worker thread also releases in its ``finally`` block,
  so a key can never stay stuck (even on errors).

Events are reported through the ``emit`` callable (thread-safe, e.g.
queue.Queue.put):

    ("countdown", seconds_left)
    ("running",)
    ("target", "self" | "blocked" | "ok")
    ("key", index, total_presses, completed_cycles)
    ("cycle", completed_cycles)
    ("error", text)
    ("stopped", reason, total_presses, completed_cycles)
        reason: "stopped" | "no_keys" | "error"
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Set

log = logging.getLogger(__name__)


class KeyboardInputError(Exception):
    """Raised by a backend when a key event could not be sent."""


class InputBackend:
    """Interface every input backend implements."""

    def key_down(self, index: int) -> None:
        raise NotImplementedError

    def key_up(self, index: int) -> None:
        raise NotImplementedError

    def foreground_state(self) -> str:
        """'ok', 'self' (our own window is active) or 'blocked' (likely UIPI)."""
        return "ok"

    def modifiers_down(self) -> bool:
        return False

    def begin_timer(self) -> None:
        pass

    def end_timer(self) -> None:
        pass


@dataclass(frozen=True)
class Step:
    index: int       # 0 = F1 ... 9 = F10
    delay_min_ms: int
    delay_max_ms: Optional[int] = None

    def __post_init__(self) -> None:
        # Keep the old Step(index, delay_ms) form usable by callers/tests.
        if self.delay_max_ms is None:
            object.__setattr__(self, "delay_max_ms", self.delay_min_ms)
        elif self.delay_min_ms > self.delay_max_ms:
            low, high = self.delay_max_ms, self.delay_min_ms
            object.__setattr__(self, "delay_min_ms", low)
            object.__setattr__(self, "delay_max_ms", high)

    @property
    def delay_ms(self) -> int:
        """Compatibility for a fixed delay; ranged steps expose their minimum."""
        return self.delay_min_ms


class Runner:
    MODIFIER_WAIT_SECONDS = 3.0

    def __init__(self, backend: InputBackend, emit: Callable[[tuple], None]) -> None:
        self._backend = backend
        self._emit = emit
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pressed: Set[int] = set()
        self._thread: Optional[threading.Thread] = None
        self._target_state = "ok"

    # ------------------------------------------------------------- control
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(
        self,
        get_steps: Callable[[], Sequence[Step]],
        get_hold_ms: Callable[[], int],
        start_delay_s: int = 0,
    ) -> bool:
        """Start running. ``get_steps`` / ``get_hold_ms`` are re-read every
        cycle, so edits made while running take effect on the next key."""
        if self.is_running():
            if not self._stop.is_set():
                return False
            self._thread.join(1.0)  # a stop is still finishing
            if self.is_running():
                return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(get_steps, get_hold_ms, int(start_delay_s)),
            name="fka-runner",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Cancel immediately and release every pressed key."""
        self._stop.set()
        self._release_all()

    # --------------------------------------------------------------- worker
    def _run(self, get_steps, get_hold_ms, start_delay_s) -> None:
        reason = "stopped"
        presses = cycles = 0
        self._target_state = "ok"
        self._backend.begin_timer()
        try:
            for remaining in range(start_delay_s, 0, -1):
                self._emit(("countdown", remaining))
                if self._stop.wait(1.0):
                    return
            self._wait_modifiers_released()
            if self._stop.is_set():
                return
            self._emit(("running",))

            while not self._stop.is_set():
                steps = get_steps()
                if not steps:
                    reason = "no_keys"
                    break
                completed = True
                for step in steps:
                    if not self._wait_for_target():
                        completed = False
                        break
                    if self._stop.is_set():
                        completed = False
                        break
                    if self._press(step.index, get_hold_ms()):
                        presses += 1
                        self._emit(("key", step.index, presses, cycles))
                    if self._stop.is_set():
                        completed = False
                        break
                    delay_ms = random.randint(step.delay_min_ms, step.delay_max_ms)
                    if self._stop.wait(max(0, delay_ms) / 1000.0):
                        completed = False
                        break
                if completed:
                    cycles += 1
                    self._emit(("cycle", cycles))
        except Exception as exc:  # backend failure or unexpected bug
            log.exception("Runner failed")
            reason = "error"
            self._emit(("error", str(exc) or exc.__class__.__name__))
        finally:
            self._release_all()
            self._backend.end_timer()
            self._emit(("stopped", reason, presses, cycles))

    def _press(self, index: int, hold_ms: int) -> bool:
        """Tap one key, holding it briefly before release."""
        with self._lock:
            if self._stop.is_set():
                return False
            self._backend.key_down(index)
            self._pressed.add(index)
        try:
            self._stop.wait(max(1, hold_ms) / 1000.0)
        finally:
            with self._lock:
                if index in self._pressed:
                    self._pressed.discard(index)
                    self._backend.key_up(index)
        return True

    def _release_all(self) -> None:
        with self._lock:
            for index in sorted(self._pressed):
                try:
                    self._backend.key_up(index)
                except Exception:
                    log.exception("Could not release key %s", index)
            self._pressed.clear()

    def _wait_for_target(self) -> bool:
        """Block while our own window has the focus. False if stopped."""
        while not self._stop.is_set():
            state = self._backend.foreground_state()
            if state != self._target_state:
                self._target_state = state
                self._emit(("target", state))
            if state != "self":
                return True
            self._stop.wait(0.1)
        return False

    def _wait_modifiers_released(self) -> None:
        """If started with a hotkey, let the user release Ctrl/Alt first so the
        target doesn't receive Ctrl+Alt+F1 instead of F1."""
        deadline = time.monotonic() + self.MODIFIER_WAIT_SECONDS
        while (
            self._backend.modifiers_down()
            and time.monotonic() < deadline
            and not self._stop.is_set()
        ):
            self._stop.wait(0.02)
