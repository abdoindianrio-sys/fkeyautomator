"""Windows global input recorder and safe macro playback engine."""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_int, c_int32, c_ssize_t, c_size_t, c_uint, c_uint32, c_void_p
from dataclasses import replace
from typing import Callable, Dict, List, Optional

from .keyboard_input import INPUT, INPUT_KEYBOARD
from .macros import Macro, MacroEvent

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT, WM_USER = 0x0012, 0x0400
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEMOVE = 0x0200
LLKHF_INJECTED, LLKHF_LOWER_IL_INJECTED = 0x10, 0x02
LLMHF_INJECTED, LLMHF_LOWER_IL_INJECTED = 0x01, 0x02
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, KEYEVENTF_EXTENDEDKEY = 0x02, 0x08, 0x01
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSE_SAMPLE_SECONDS = 0.010
MOUSE_FLAGS = {
    ("left", "down"): 0x0002, ("left", "up"): 0x0004,
    ("right", "down"): 0x0008, ("right", "up"): 0x0010,
    ("middle", "down"): 0x0020, ("middle", "up"): 0x0040,
    ("x1", "down"): 0x0080, ("x1", "up"): 0x0100,
    ("x2", "down"): 0x0080, ("x2", "up"): 0x0100,
}

_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_LRESULT = c_ssize_t


class _POINT(Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class _MSG(Structure):
    _fields_ = [
        ("hwnd", c_void_p), ("message", c_uint32), ("wParam", c_size_t),
        ("lParam", c_ssize_t), ("time", c_uint32), ("pt", _POINT),
    ]


class _KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("vkCode", c_uint32), ("scanCode", c_uint32),
        ("flags", c_uint32), ("time", c_uint32), ("dwExtraInfo", c_size_t),
    ]


class _MSLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("pt", _POINT), ("mouseData", c_uint32), ("flags", c_uint32),
        ("time", c_uint32), ("dwExtraInfo", c_size_t),
    ]


_HOOKPROC = _WINFUNCTYPE(_LRESULT, c_int, c_size_t, c_ssize_t)


class GlobalRecorder:
    """Records physical key/button transitions and always passes them onward."""

    def __init__(self, own_pid: Optional[int] = None) -> None:
        self.own_pid = own_pid or (os_getpid() if IS_WINDOWS else 0)
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._closing = threading.Event()
        self._ready = threading.Event()
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._events: List[MacroEvent] = []
        self._down: Dict[tuple, MacroEvent] = {}
        self._last_time: Optional[float] = None
        self._last_move_at: Optional[float] = None
        self._last_move: Optional[tuple] = None
        self._pending_move: Optional[tuple] = None
        self._recording = False
        self._callbacks = []
        self._hooks = []
        self._user32 = None

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if not IS_WINDOWS:
            raise OSError("Global recording is available on Windows only")
        if self._thread and self._thread.is_alive():
            raise RuntimeError("recorder is already running")
        self._events, self._down, self._last_time = [], {}, None
        self._last_move_at, self._last_move, self._pending_move = None, None, None
        self._closing.clear()
        self._ready.clear()
        self._error = None
        self._recording = True
        self._thread = threading.Thread(target=self._hook_loop, name="fka-recorder", daemon=True)
        self._thread.start()
        if not self._ready.wait(3.0):
            self._recording = False
            self.stop()
            raise OSError("Windows input hooks did not start")
        if self._error:
            self._recording = False
            self.stop()
            raise OSError(str(self._error))

    def stop(self) -> List[MacroEvent]:
        self._recording = False
        if self._thread and self._thread.is_alive() and self._thread_id:
            self._closing.set()
            try:
                self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                log.exception("Could not stop recorder hook thread")
            self._thread.join(3.0)
        with self._lock:
            now = time.perf_counter()
            self._flush_pending_move_locked()
            for event in list(self._down.values()):
                self._append_locked(event.key_up_copy(), now)
            self._down.clear()
            return list(self._events)

    def _hook_loop(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.SetWindowsHookExW.argtypes = [c_int, _HOOKPROC, c_void_p, c_uint32]
            user32.SetWindowsHookExW.restype = c_void_p
            user32.UnhookWindowsHookEx.argtypes = [c_void_p]
            user32.CallNextHookEx.argtypes = [c_void_p, c_int, c_size_t, c_ssize_t]
            user32.CallNextHookEx.restype = _LRESULT
            user32.GetMessageW.argtypes = [POINTER(_MSG), c_void_p, c_uint, c_uint]
            user32.GetMessageW.restype = c_int
            user32.PeekMessageW.argtypes = [POINTER(_MSG), c_void_p, c_uint, c_uint, c_uint]
            user32.PostThreadMessageW.argtypes = [c_uint32, c_uint, c_size_t, c_ssize_t]
            user32.GetForegroundWindow.restype = c_void_p
            user32.GetWindowThreadProcessId.argtypes = [c_void_p, POINTER(c_uint32)]
            kernel32.GetCurrentThreadId.restype = c_uint32
            kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel32.GetModuleHandleW.restype = c_void_p
            msg = _MSG()
            user32.PeekMessageW(byref(msg), None, WM_USER, WM_USER, 0)
            self._thread_id = kernel32.GetCurrentThreadId()
            self._user32 = user32

            def callback(code, wparam, lparam):
                try:
                    if code >= 0 and self._recording and not self._own_window_is_foreground():
                        if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                            info = ctypes.cast(lparam, POINTER(_KBDLLHOOKSTRUCT)).contents
                            if not (info.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED)):
                                down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                                self._record(MacroEvent(
                                    "key", "key", "down" if down else "up", 0,
                                    int(info.scanCode), int(info.vkCode), bool(info.flags & 1),
                                ))
                        elif wparam in (WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN,
                                       WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP,
                                       WM_XBUTTONDOWN, WM_XBUTTONUP):
                            info = ctypes.cast(lparam, POINTER(_MSLLHOOKSTRUCT)).contents
                            if not (info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED)):
                                mapping = {
                                    WM_LBUTTONDOWN: ("left", "down"), WM_LBUTTONUP: ("left", "up"),
                                    WM_RBUTTONDOWN: ("right", "down"), WM_RBUTTONUP: ("right", "up"),
                                    WM_MBUTTONDOWN: ("middle", "down"), WM_MBUTTONUP: ("middle", "up"),
                                }
                                if wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                                    button = "x1" if (info.mouseData >> 16) == 1 else "x2"
                                    action = "down" if wparam == WM_XBUTTONDOWN else "up"
                                    pair = (button, action)
                                else:
                                    pair = mapping[wparam]
                                self._record(MacroEvent("mouse", pair[0], pair[1]))
                        elif wparam == WM_MOUSEMOVE:
                            info = ctypes.cast(lparam, POINTER(_MSLLHOOKSTRUCT)).contents
                            if not (info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED)):
                                self._record_pointer(int(info.pt.x), int(info.pt.y))
                except Exception:
                    log.exception("Input recorder callback failed")
                return user32.CallNextHookEx(None, code, wparam, lparam)

            hook_callback = _HOOKPROC(callback)
            self._callbacks.append(hook_callback)  # keep callback alive
            module = kernel32.GetModuleHandleW(None)
            keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_callback, module, 0)
            mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, hook_callback, module, 0)
            if not keyboard_hook or not mouse_hook:
                if keyboard_hook:
                    user32.UnhookWindowsHookEx(keyboard_hook)
                if mouse_hook:
                    user32.UnhookWindowsHookEx(mouse_hook)
                raise OSError("SetWindowsHookEx failed (%d)" % ctypes.get_last_error())
            self._hooks = [keyboard_hook, mouse_hook]
            self._ready.set()
            while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
                pass
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            self._recording = False
            if self._user32:
                for hook in self._hooks:
                    try:
                        self._user32.UnhookWindowsHookEx(hook)
                    except Exception:
                        log.exception("Could not unhook recorder")
            self._hooks = []
            self._thread_id = 0

    def _own_window_is_foreground(self) -> bool:
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return False
            pid = c_uint32(0)
            self._user32.GetWindowThreadProcessId(hwnd, byref(pid))
            return pid.value == self.own_pid
        except Exception:
            return False

    def _record(self, event: MacroEvent) -> None:
        now = time.perf_counter()
        with self._lock:
            if len(self._events) >= 19_700:
                self._recording = False
                return
            self._flush_pending_move_locked()
            if event.action == "down":
                if event.identity in self._down:  # ignore keyboard auto-repeat
                    return
                self._down[event.identity] = event
            elif event.identity not in self._down:
                return
            self._append_locked(event, now)
            if event.action == "up":
                self._down.pop(event.identity, None)

    def _record_pointer(self, x: int, y: int, now: Optional[float] = None) -> None:
        now = time.perf_counter() if now is None else now
        point = (int(x), int(y))
        with self._lock:
            if len(self._events) >= 19_700:
                self._recording = False
                return
            if point == self._last_move:
                self._pending_move = None
                return
            if self._pending_move and point == self._pending_move[:2]:
                return
            if self._last_move_at is not None and now - self._last_move_at < MOUSE_SAMPLE_SECONDS:
                self._pending_move = (point[0], point[1], now)
                return
            # Keep only the newest point when a sampling interval elapses.
            self._pending_move = None
            self._append_locked(MacroEvent("mouse", "move", "move", x=point[0], y=point[1]), now)
            self._last_move, self._last_move_at = point, now

    def _flush_pending_move_locked(self) -> None:
        if self._pending_move is None:
            return
        x, y, now = self._pending_move
        self._pending_move = None
        point = (x, y)
        if point != self._last_move and len(self._events) < 19_700:
            self._append_locked(MacroEvent("mouse", "move", "move", x=x, y=y), now)
            self._last_move, self._last_move_at = point, now

    def _append_locked(self, event: MacroEvent, now: float) -> None:
        event.delay_ms = 0 if self._last_time is None else min(
            3_600_000, max(0, round((now - self._last_time) * 1000))
        )
        self._events.append(event)
        self._last_time = now


def os_getpid() -> int:
    try:
        return int(ctypes.windll.kernel32.GetCurrentProcessId())
    except Exception:
        return 0


class WindowsMacroIO:
    """SendInput adapter for arbitrary captured keyboard and mouse buttons."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise OSError("Macro playback is available on Windows only")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.winmm = ctypes.WinDLL("winmm")
        self.user32.SendInput.argtypes = [c_uint, POINTER(INPUT), c_int]
        self.user32.SendInput.restype = c_uint
        self.user32.GetForegroundWindow.restype = c_void_p
        self.user32.GetWindowThreadProcessId.argtypes = [c_void_p, POINTER(c_uint32)]
        self.user32.GetSystemMetrics.argtypes = [c_int]
        self.user32.GetSystemMetrics.restype = c_int
        self.own_pid = os_getpid()

    def foreground_state(self) -> str:
        try:
            hwnd = self.user32.GetForegroundWindow()
            if not hwnd:
                return "ok"
            pid = c_uint32(0)
            self.user32.GetWindowThreadProcessId(hwnd, byref(pid))
            return "self" if pid.value == self.own_pid else "ok"
        except Exception:
            return "ok"

    def send(self, event: MacroEvent) -> None:
        item = INPUT()
        if event.device == "mouse" and event.code == "move":
            left = self.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
            top = self.user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
            width = max(1, self.user32.GetSystemMetrics(78))
            height = max(1, self.user32.GetSystemMetrics(79))
            x = min(max(event.x, left), left + width - 1)
            y = min(max(event.y, top), top + height - 1)
            item.type = 0
            item.mi.dx = round((x - left) * 65535 / max(1, width - 1))
            item.mi.dy = round((y - top) * 65535 / max(1, height - 1))
            item.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        elif event.device == "key":
            item.type = INPUT_KEYBOARD
            item.ki.wVk = 0 if event.scan_code else event.virtual_key
            item.ki.wScan = event.scan_code
            flags = KEYEVENTF_SCANCODE if event.scan_code else 0
            if event.extended:
                flags |= KEYEVENTF_EXTENDEDKEY
            if event.action == "up":
                flags |= KEYEVENTF_KEYUP
            item.ki.dwFlags = flags
        else:
            item.type = 0  # INPUT_MOUSE
            item.mi.dwFlags = MOUSE_FLAGS[(event.code, event.action)]
            if event.code == "x1":
                item.mi.mouseData = 1
            elif event.code == "x2":
                item.mi.mouseData = 2
        sent = self.user32.SendInput(1, byref(item), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError("SendInput failed (error %d)" % ctypes.get_last_error())

    def begin_timer(self) -> None:
        try:
            self.winmm.timeBeginPeriod(1)
        except Exception:
            pass

    def end_timer(self) -> None:
        try:
            self.winmm.timeEndPeriod(1)
        except Exception:
            pass


class MacroPlayer:
    def __init__(self, io_backend, emit: Optional[Callable[[tuple], None]] = None) -> None:
        self.io = io_backend
        self.emit = emit or (lambda event: None)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pressed: Dict[tuple, MacroEvent] = {}
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, macro: Macro, loop: Optional[bool] = None) -> bool:
        if self.running or not macro.events:
            return False
        if self._thread and self._thread.is_alive():
            self._thread.join(1.0)
            if self._thread.is_alive():
                return False
        self._stop.clear()
        snapshot = Macro.from_dict(macro.to_dict())
        repeat_count = (
            None if snapshot.repeat_forever else snapshot.repeat_count
        ) if loop is None else (None if loop else 1)
        self._thread = threading.Thread(
            target=self._run, args=(snapshot, repeat_count), name="fka-macro-player", daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._release_all()

    def _run(self, macro: Macro, repeat_count: Optional[int]) -> None:
        reason = "stopped"
        timer_started = False
        try:
            self.io.begin_timer()
            timer_started = True
            completed = 0
            while not self._stop.is_set():
                for index, event in enumerate(macro.events):
                    while (not self._stop.is_set()
                           and getattr(self.io, "foreground_state", lambda: "ok")() == "self"):
                        self._stop.wait(0.1)
                    if self._stop.is_set():
                        break
                    delay = 0 if index == 0 else event.delay_ms
                    if macro.timing_mode == "fixed" and index > 0:
                        delay = macro.fixed_delay_ms
                    if self._stop.wait(max(0, delay) / 1000.0):
                        break
                    with self._lock:
                        if self._stop.is_set():
                            break
                        self.io.send(event)
                        if event.action == "down":
                            self._pressed[event.identity] = event
                        elif event.action == "up":
                            self._pressed.pop(event.identity, None)
                else:
                    completed += 1
                    if repeat_count is None or completed < repeat_count:
                        continue
                    reason = "completed"
                break
        except Exception as exc:
            log.exception("Macro playback failed")
            reason = "error"
            self.emit(("macro_error", str(exc) or exc.__class__.__name__))
        finally:
            self._release_all()
            if timer_started:
                self.io.end_timer()
            self.emit(("macro_stopped", reason))

    def _release_all(self) -> None:
        with self._lock:
            for event in list(self._pressed.values()):
                try:
                    self.io.send(event.key_up_copy())
                except Exception:
                    log.exception("Could not release macro input %r", event.identity)
            self._pressed.clear()

