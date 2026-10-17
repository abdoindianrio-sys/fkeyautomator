"""Application logic with no GUI code, so it can be unit-tested anywhere.

The window (ui.py) is a thin view: it forwards user actions to this
controller and, on a timer, calls ``tick()`` and re-draws from ``state``
whenever ``state.version`` changed.

Threading: the runner and the hotkey run on their own threads.  They only
talk to the controller through ``self.events`` (a thread-safe queue) that
the UI thread drains in ``tick()``.  Settings are edited on the UI thread
only; the runner reads an immutable snapshot (a tuple) that is replaced
atomically, so it never sees a half-edited sequence.
"""
from __future__ import annotations

import logging
import os
import queue
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from . import settings as cfg
from .engine import InputBackend, Runner, Step
from .macro_runtime import MacroPlayer
from .macros import MAX_MACROS, Macro, MacroStore, normalize_hotkey

log = logging.getLogger(__name__)


@dataclass
class UiState:
    running: bool = False
    phase: str = "ready"        # ready | countdown | running | waiting | stopped | error
    countdown: int = 0
    message_kind: str = ""      # "" | "info" | "warn" | "error"
    message_key: str = ""
    message_detail: str = ""
    active_key: Optional[int] = None
    presses: int = 0
    cycles: int = 0
    hotkey_ok: Optional[bool] = None
    macro_recording: bool = False
    macro_playing: bool = False
    macro_hotkey_ok: Optional[bool] = None
    version: int = 0


class Controller:
    FLASH_SECONDS = 0.18     # how long a key cap stays lit after a press
    SAVE_DELAY_SECONDS = 0.5  # debounce for writing settings.json

    def __init__(
        self,
        backend: InputBackend,
        config_path: Optional[str] = None,
        hotkey_factory: Optional[Callable] = None,
        admin: bool = False,
        relaunch: Optional[Callable[[], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        macro_store: Optional[MacroStore] = None,
        macro_recorder=None,
        macro_player: Optional[MacroPlayer] = None,
        macro_backend=None,
        macro_hotkey_factory: Optional[Callable] = None,
    ) -> None:
        self._config_path = config_path
        self._clock = clock
        self._relaunch = relaunch
        self.admin = admin
        self.settings = cfg.load(config_path)
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.runner = Runner(backend, self.events.put)
        macro_path = os.path.join(os.path.dirname(config_path), "macros.json") if config_path else None
        self.macro_store = macro_store or MacroStore(macro_path)
        self.macro_recorder = macro_recorder
        self.macro_player = macro_player or (MacroPlayer(macro_backend, self.events.put) if macro_backend else None)
        self.macro_hotkey = (
            macro_hotkey_factory(
                self._on_macro_hotkey, self._on_macro_hotkey_status,
                hotkey=self.macro_store.hotkey, hotkey_id=0x4B42,
            ) if macro_hotkey_factory else None
        )
        self._recording_macro_id: Optional[str] = None
        self._selected_macro_id: Optional[str] = (
            self.macro_store.macros[0].id if self.macro_store.macros else None
        )
        self.state = UiState()
        self._rendered_version = -1
        self._steps: Tuple[Step, ...] = ()
        self._hold_ms = cfg.HOLD_DEFAULT
        self._dirty_since: Optional[float] = None
        self._flash_until = 0.0
        self.hotkey = (
            hotkey_factory(self._on_hotkey, self._on_hotkey_status)
            if hotkey_factory
            else None
        )
        self._rebuild_snapshot()

    # ----------------------------------------------------------- lifecycle
    def start_services(self) -> None:
        if self.hotkey:
            self.hotkey.start()
        if self.macro_hotkey:
            self.macro_hotkey.start()

    def close(self) -> None:
        self.runner.stop()
        if self.macro_recorder and self.macro_recorder.recording:
            self.stop_recording()
        if self.macro_player:
            self.macro_player.stop()
        if self.hotkey:
            self.hotkey.stop()
        if self.macro_hotkey:
            self.macro_hotkey.stop()
        self.save_now()
        self.save_macros()

    # ------------------------------------------------ snapshot for the runner
    def _rebuild_snapshot(self) -> None:
        self._steps = tuple(
            Step(
                i,
                key.fixed_delay_ms if key.fixed_delay else key.delay_min_ms,
                key.fixed_delay_ms if key.fixed_delay else key.delay_max_ms,
            )
            for i, key in enumerate(self.settings.keys)
            if key.enabled
        )
        self._hold_ms = cfg.HOLD_DEFAULT

    def get_steps(self) -> Tuple[Step, ...]:      # called from the runner thread
        return self._steps

    def get_hold_ms(self) -> int:                 # called from the runner thread
        return self._hold_ms

    # ------------------------------------------------------- settings edits
    def set_enabled(self, index: int, enabled: bool) -> None:
        self.settings.keys[index].enabled = bool(enabled)
        self._changed()

    def set_fixed_delay(self, index: int, fixed: bool) -> None:
        self.settings.keys[index].fixed_delay = bool(fixed)
        self._changed()

    def set_fixed_delay_ms(self, index: int, delay_ms: int) -> None:
        self.settings.keys[index].fixed_delay_ms = cfg.clamp_int(
            delay_ms, cfg.DELAY_MIN, cfg.DELAY_MAX, cfg.DELAY_DEFAULT
        )
        self._changed()

    def set_delay_min(self, index: int, delay_ms: int) -> None:
        key = self.settings.keys[index]
        value = cfg.clamp_int(
            delay_ms, cfg.DELAY_MIN, cfg.DELAY_MAX, cfg.DELAY_DEFAULT
        )
        key.delay_min_ms = value
        key.delay_max_ms = max(key.delay_max_ms, value)
        self._changed()

    def set_delay_max(self, index: int, delay_ms: int) -> None:
        key = self.settings.keys[index]
        value = cfg.clamp_int(
            delay_ms, cfg.DELAY_MIN, cfg.DELAY_MAX, cfg.DELAY_DEFAULT
        )
        key.delay_max_ms = value
        key.delay_min_ms = min(key.delay_min_ms, value)
        self._changed()

    def set_delay(self, index: int, delay_ms: int) -> None:
        """Set a fixed delay for compatibility with earlier callers."""
        value = cfg.clamp_int(
            delay_ms, cfg.DELAY_MIN, cfg.DELAY_MAX, cfg.DELAY_DEFAULT
        )
        key = self.settings.keys[index]
        key.delay_min_ms = key.delay_max_ms = value
        self._changed()

    def set_start_delay(self, seconds: int) -> None:
        self.settings.start_delay_s = cfg.clamp_int(
            seconds, cfg.START_MIN, cfg.START_MAX, cfg.START_DEFAULT
        )
        self._changed()

    def set_hold(self, hold_ms: int) -> None:
        self.settings.hold_ms = cfg.clamp_int(
            hold_ms, cfg.HOLD_MIN, cfg.HOLD_MAX, cfg.HOLD_DEFAULT
        )
        self._changed()

    def _changed(self) -> None:
        self._rebuild_snapshot()
        self._dirty_since = self._clock()

    # ------------------------------------------------------------ persistence
    def save_now(self) -> None:
        self._dirty_since = None
        if not cfg.save(self.settings, self._config_path):
            self._set_message("warn", "save_fail")

    # --------------------------------------------------------------- actions
    def start(self) -> bool:
        if self.state.running:
            return False
        if self.state.macro_recording or self.state.macro_playing or (self.macro_player and self.macro_player.running):
            self._set_message("warn", "automation_busy")
            return False
        if not self._steps:
            self._set_message("warn", "no_keys")
            return False
        if not self.runner.start(self.get_steps, self.get_hold_ms, 0):
            return False
        self.state.running = True
        self.state.phase = "running"
        self.state.countdown = 0
        self.state.presses = 0
        self.state.cycles = 0
        self.state.active_key = None
        self._set_message("", "")
        self._bump()
        return True

    def stop(self) -> None:
        """Immediate: cancels waits and releases pressed keys right now."""
        self.runner.stop()

    # --------------------------------------------------------------- macros
    def create_macro(self, name: str = "") -> Macro:
        if len(self.macro_store.macros) >= MAX_MACROS:
            raise ValueError("وصلت للحد الأقصى لعدد الماكروز")
        number = 1
        if not name.strip():
            existing = {macro.name for macro in self.macro_store.macros}
            while "ماكرو %d" % number in existing:
                number += 1
            name = "ماكرو %d" % number
        macro = Macro(uuid.uuid4().hex, name)
        self.macro_store.macros.append(macro)
        self._selected_macro_id = macro.id
        self.save_macros()
        self._bump()
        return macro

    def delete_macro(self, macro_id: str) -> None:
        if self._recording_macro_id == macro_id:
            self.stop_recording()
        if self.macro_player and self.macro_player.running and self._selected_macro_id == macro_id:
            self.stop_macro()
        self.macro_store.macros = [m for m in self.macro_store.macros if m.id != macro_id]
        if self._selected_macro_id == macro_id:
            self._selected_macro_id = (
                self.macro_store.macros[0].id if self.macro_store.macros else None
            )
        self.save_macros()
        self._bump()

    def select_macro(self, macro_id: Optional[str]) -> None:
        if any(m.id == macro_id for m in self.macro_store.macros) and macro_id != self._selected_macro_id:
            self._selected_macro_id = macro_id
            self._bump()

    def get_macro(self, macro_id: Optional[str] = None) -> Optional[Macro]:
        macro_id = macro_id or self._selected_macro_id
        return next((m for m in self.macro_store.macros if m.id == macro_id), None)

    def update_macro(self, macro_id: str, **changes) -> bool:
        macro = self.get_macro(macro_id)
        if not macro:
            return False
        if "name" in changes:
            macro.name = str(changes["name"]).strip()[:80] or "ماكرو جديد"
        if "timing_mode" in changes:
            macro.timing_mode = "fixed" if changes["timing_mode"] == "fixed" else "recorded"
        if "fixed_delay_ms" in changes:
            macro.fixed_delay_ms = cfg.clamp_int(changes["fixed_delay_ms"], 0, cfg.DELAY_MAX, 100)
        if "repeat_count" in changes:
            from .macros import MAX_REPEAT_COUNT
            macro.repeat_count = cfg.clamp_int(changes["repeat_count"], 1, MAX_REPEAT_COUNT, 1)
        if "repeat_forever" in changes:
            macro.repeat_forever = bool(changes["repeat_forever"])
        if "events" in changes:
            macro.events = list(changes["events"])
        self.save_macros()
        self._bump()
        return True

    def start_recording(self, macro_id: Optional[str] = None) -> bool:
        if not self.macro_recorder:
            self._set_message("error", "macro_unavailable")
            return False
        if self.state.running or self.state.macro_recording or self.state.macro_playing or (self.macro_player and self.macro_player.running):
            self._set_message("warn", "automation_busy")
            return False
        macro = self.get_macro(macro_id)
        if not macro:
            macro = self.create_macro()
        try:
            self.macro_recorder.start()
        except Exception as exc:
            log.exception("Could not start macro recording")
            self._set_message("error", "macro_error", detail=str(exc))
            return False
        macro.events = []
        self._recording_macro_id = macro.id
        self._selected_macro_id = macro.id
        self.state.macro_recording = True
        self._set_message("", "")
        self._bump()
        return True

    def stop_recording(self) -> bool:
        if not self.state.macro_recording or not self.macro_recorder:
            return False
        events = self.macro_recorder.stop()
        macro = self.get_macro(self._recording_macro_id)
        if macro:
            macro.events = list(events)
            self.save_macros()
        self._recording_macro_id = None
        self.state.macro_recording = False
        self._bump()
        return True

    def play_macro(self, macro_id: Optional[str] = None, loop: Optional[bool] = None) -> bool:
        macro = self.get_macro(macro_id)
        if not self.macro_player or not macro or not macro.events:
            self._set_message("warn", "macro_empty")
            return False
        if self.state.running or self.state.macro_recording or self.state.macro_playing:
            self._set_message("warn", "automation_busy")
            return False
        if not self.macro_player.start(macro, loop):
            self._set_message("warn", "automation_busy")
            return False
        self._selected_macro_id = macro.id
        self.state.macro_playing = True
        self._set_message("", "")
        self._bump()
        return True

    def stop_macro(self) -> None:
        if self.macro_player:
            self.macro_player.stop()

    def import_macro(self, path: str) -> Macro:
        macro = self.macro_store.import_macro(path)
        self.macro_store.macros.append(macro)
        self._selected_macro_id = macro.id
        self.save_macros()
        self._bump()
        return macro

    def set_macro_hotkey(self, value: str) -> str:
        chord = normalize_hotkey(value)
        if self.macro_hotkey:
            self.macro_hotkey.set_hotkey(chord)
        self.macro_store.hotkey = chord
        self.save_macros()
        self._bump()
        return chord

    def save_macros(self) -> bool:
        if not self.macro_store.save():
            self._set_message("warn", "macro_save_fail", bump=False)
            return False
        return True

    def relaunch_as_admin(self) -> bool:
        """Save, stop, then ask Windows for an elevated copy. True -> caller should quit."""
        self.runner.stop()
        self.save_now()
        ok = bool(self._relaunch and self._relaunch())
        if not ok:
            self._set_message("warn", "relaunch_fail")
        return ok

    # --------------------------------------------- callbacks from other threads
    def _on_hotkey(self) -> None:
        if self.runner.is_running():
            self.runner.stop()                  # stop right here, no UI round trip
        else:
            self.events.put(("hotkey_start",))  # start must happen on the UI thread

    def _on_hotkey_status(self, ok: bool) -> None:
        self.events.put(("hotkey_status", ok))

    def _on_macro_hotkey(self) -> None:
        if self.macro_player and self.macro_player.running:
            self.macro_player.stop()
        else:
            self.events.put(("macro_hotkey",))

    def _on_macro_hotkey_status(self, ok: bool) -> None:
        self.events.put(("macro_hotkey_status", ok))

    # ------------------------------------------------------------------ tick
    def tick(self) -> bool:
        """Process pending events. Returns True if the view must be redrawn."""
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass

        now = self._clock()
        if self.state.active_key is not None and now >= self._flash_until:
            self.state.active_key = None
            self._bump()
        if self._dirty_since is not None and now - self._dirty_since >= self.SAVE_DELAY_SECONDS:
            self.save_now()

        changed = self.state.version != self._rendered_version
        self._rendered_version = self.state.version
        return changed

    # --------------------------------------------------------------- internals
    def _handle(self, event: tuple) -> None:
        kind = event[0]
        st = self.state
        if kind == "countdown":
            st.phase, st.countdown = "countdown", event[1]
        elif kind == "running":
            st.phase = "running"
        elif kind == "target":
            if event[1] == "self":
                st.phase = "waiting"
                self._set_message("info", "self_focus", bump=False)
            else:
                st.phase = "running"
                if event[1] == "blocked":
                    self._set_message("warn", "blocked", bump=False)
                elif st.message_key in ("self_focus", "blocked"):
                    self._set_message("", "", bump=False)
        elif kind == "key":
            st.active_key, st.presses, st.cycles = event[1], event[2], event[3]
            self._flash_until = self._clock() + self.FLASH_SECONDS
        elif kind == "cycle":
            st.cycles = event[1]
        elif kind == "error":
            self._set_message("error", "error", detail=event[1], bump=False)
        elif kind == "stopped":
            _, reason, presses, cycles = event
            st.running = False
            st.active_key = None
            st.presses, st.cycles = presses, cycles
            if reason == "error":
                st.phase = "error"
            else:
                st.phase = "stopped"
                if reason == "no_keys":
                    self._set_message("warn", "all_disabled", bump=False)
                elif st.message_key in ("self_focus", "blocked"):
                    self._set_message("", "", bump=False)
        elif kind == "hotkey_start":
            self.start()
        elif kind == "hotkey_status":
            st.hotkey_ok = bool(event[1])
            if not st.hotkey_ok:
                self._set_message("warn", "hotkey_fail", bump=False)
        elif kind == "macro_hotkey":
            self.play_macro(self._selected_macro_id)
        elif kind == "macro_hotkey_status":
            st.macro_hotkey_ok = bool(event[1])
            if not st.macro_hotkey_ok:
                self._set_message("warn", "macro_hotkey_fail", bump=False)
        elif kind == "macro_stopped":
            st.macro_playing = False
            if event[1] == "error":
                st.phase = "error"
        elif kind == "macro_error":
            self._set_message("error", "macro_error", detail=event[1], bump=False)
        self._bump()

    def _set_message(self, kind: str, key: str, detail: str = "", bump: bool = True) -> None:
        st = self.state
        st.message_kind, st.message_key, st.message_detail = kind, key, detail
        if bump:
            self._bump()

    def _bump(self) -> None:
        self.state.version += 1
