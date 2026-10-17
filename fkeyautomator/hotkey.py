"""System-wide start/stop hotkey (Ctrl+Alt+F12).

While a game or another app has the focus, the app's own window cannot be
clicked without leaving that app, so a global hotkey is the practical way to
start/stop from inside it.  RegisterHotKey uses the layout-independent
virtual key F12, so it also works with an Arabic keyboard layout active.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_int, c_int32, c_size_t, c_ssize_t, c_uint, c_uint32, c_void_p
from typing import Callable, Optional

log = logging.getLogger(__name__)

HOTKEY_LABEL = "Ctrl + Alt + F12"
MACRO_HOTKEY_LABEL = "Ctrl + Shift + F12"

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_F12 = 0x7B
WM_HOTKEY, WM_QUIT, WM_USER = 0x0312, 0x0012, 0x0400
PM_NOREPEAT_FLAG = 0  # PM_NOREMOVE
HOTKEY_ID = 0x4B41
MACRO_HOTKEY_ID = 0x4B42


def parse_hotkey(value: str) -> tuple:
    """Parse a user-editable chord into RegisterHotKey flags and a VK code."""
    parts = [part.strip().lower() for part in value.replace(" ", "").split("+")]
    modifiers = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL,
                 "alt": MOD_ALT, "shift": 0x0004}
    flags = 0
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError("unsupported hotkey modifier")
        if flags & modifiers[part]:
            raise ValueError("duplicate hotkey modifier")
        flags |= modifiers[part]
    if not flags or len(parts) < 2:
        raise ValueError("hotkey requires a modifier and a key")
    key = parts[-1].upper()
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        virtual_key = 0x6F + int(key[1:])
    elif len(key) == 1 and "A" <= key <= "Z":
        virtual_key = ord(key)
    else:
        raise ValueError("unsupported hotkey key")
    label_modifiers = []
    if flags & MOD_CONTROL:
        label_modifiers.append("Ctrl")
    if flags & MOD_ALT:
        label_modifiers.append("Alt")
    if flags & 0x0004:
        label_modifiers.append("Shift")
    return flags, virtual_key, " + ".join(label_modifiers + [key])


class _POINT(Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class _MSG(Structure):
    _fields_ = [
        ("hwnd", c_void_p),
        ("message", c_uint32),
        ("wParam", c_size_t),
        ("lParam", c_ssize_t),
        ("time", c_uint32),
        ("pt", _POINT),
    ]


class GlobalHotkey:
    def __init__(
        self,
        on_pressed: Callable[[], None],
        on_status: Optional[Callable[[bool], None]] = None,
        hotkey: str = HOTKEY_LABEL,
        hotkey_id: int = HOTKEY_ID,
    ) -> None:
        self._on_pressed = on_pressed
        self._on_status = on_status
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._closing = threading.Event()
        self.registered = False
        self.hotkey = hotkey
        self.hotkey_id = hotkey_id

    def start(self) -> None:
        if sys.platform != "win32" or (self._thread is not None and self._thread.is_alive()):
            return
        self._closing.clear()
        self._thread = threading.Thread(target=self._loop, name="fka-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._closing.set()
        if sys.platform != "win32" or not self._thread_id:
            return
        try:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            if self._thread and self._thread is not threading.current_thread():
                self._thread.join(1.5)
        except Exception:
            log.exception("Could not stop hotkey thread")

    def set_hotkey(self, hotkey: str) -> None:
        """Re-register with a new chord while preserving this listener."""
        parse_hotkey(hotkey)
        was_started = self._thread is not None
        self.stop()
        self.hotkey = hotkey
        if was_started:
            self.start()

    # ---------------------------------------------------------------- thread
    def _loop(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        user32.RegisterHotKey.argtypes = [c_void_p, c_int, c_uint, c_uint]
        user32.RegisterHotKey.restype = c_int
        user32.UnregisterHotKey.argtypes = [c_void_p, c_int]
        user32.GetMessageW.argtypes = [POINTER(_MSG), c_void_p, c_uint, c_uint]
        user32.GetMessageW.restype = c_int
        user32.PeekMessageW.argtypes = [POINTER(_MSG), c_void_p, c_uint, c_uint, c_uint]
        user32.PeekMessageW.restype = c_int
        user32.PostThreadMessageW.argtypes = [c_uint32, c_uint, c_size_t, c_ssize_t]
        kernel32.GetCurrentThreadId.restype = c_uint32

        msg = _MSG()
        # Touch the message queue so PostThreadMessage(WM_QUIT) can reach us.
        user32.PeekMessageW(byref(msg), None, WM_USER, WM_USER, PM_NOREPEAT_FLAG)
        self._thread_id = kernel32.GetCurrentThreadId()

        ok = False
        try:
            modifiers, virtual_key, _label = parse_hotkey(self.hotkey)
        except ValueError:
            self._on_status(False) if self._on_status else None
            return
        # Retry briefly: after "restart as admin" the old instance may still
        # hold the hotkey for a moment.
        for _ in range(10):
            if self._closing.is_set():
                return
            if user32.RegisterHotKey(None, self.hotkey_id, modifiers | MOD_NOREPEAT, virtual_key):
                ok = True
                break
            time.sleep(0.3)
        self.registered = ok
        if self._on_status:
            try:
                self._on_status(ok)
            except Exception:
                log.exception("hotkey status callback failed")
        if not ok:
            return
        try:
            while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    try:
                        self._on_pressed()
                    except Exception:
                        log.exception("hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)
