"""Keyboard injection for Windows using SendInput.

Why SendInput + scan codes
--------------------------
* SendInput puts events into the same system input queue a real keyboard
  uses, so they reach whichever window currently has the keyboard focus
  (desktop apps, browsers, and games that read input via Win32 messages,
  Raw Input or DirectInput).
* KEYEVENTF_SCANCODE sends the *hardware scan code* (what a physical
  keyboard sends).  DirectInput / many games read scan codes and ignore
  virtual-key codes, so this is the most compatible mode.  Windows fills in
  the matching virtual key itself, so normal apps see F1..F10 as usual.

Known limits (also documented in README)
----------------------------------------
* UIPI: a normal (non-elevated) process cannot inject input into a window
  that runs as Administrator.  Windows does NOT report this as an error,
  so we detect it heuristically (see foreground_state) and warn the user.
* Anti-cheat drivers (e.g. kernel-level ones) may ignore or flag injected
  input.  Nothing user-mode can do about that.

The structure definitions use fixed-size ctypes types (not wintypes) so the
layout can be verified on any platform in the unit tests.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, Structure, Union, byref, c_int, c_int32, c_size_t, c_uint, c_uint16, c_uint32, c_void_p, c_wchar_p

from .engine import InputBackend, KeyboardInputError

IS_WINDOWS = sys.platform == "win32"

F_KEY_NAMES = tuple("F%d" % n for n in range(1, 11))
# Hardware scan codes, set 1: F1..F10 = 0x3B..0x44 (not extended keys).
SCAN_CODES = tuple(range(0x3B, 0x45))

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

ERROR_ACCESS_DENIED = 5
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C


class KEYBDINPUT(Structure):
    _fields_ = [
        ("wVk", c_uint16),
        ("wScan", c_uint16),
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_int32),
        ("dy", c_int32),
        ("mouseData", c_uint32),
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class HARDWAREINPUT(Structure):
    _fields_ = [("uMsg", c_uint32), ("wParamL", c_uint16), ("wParamH", c_uint16)]


class _INPUT_UNION(Union):
    # MOUSEINPUT must be part of the union: it is the largest member and
    # determines sizeof(INPUT) (40 bytes on 64-bit, 28 on 32-bit).
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", c_uint32), ("u", _INPUT_UNION)]


def expected_input_size() -> int:
    return 40 if ctypes.sizeof(c_size_t) == 8 else 28


def build_key_event(index: int, key_up: bool) -> INPUT:
    """Build the INPUT structure for one F-key event (index 0 = F1)."""
    if not 0 <= index < len(SCAN_CODES):
        raise ValueError("key index out of range: %r" % (index,))
    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.ki.wVk = 0
    event.ki.wScan = SCAN_CODES[index]
    event.ki.dwFlags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    event.ki.time = 0
    event.ki.dwExtraInfo = 0
    return event


class WindowsKeyboard(InputBackend):
    """Real backend: injects keys through user32.SendInput."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise OSError("WindowsKeyboard can only be used on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._winmm = ctypes.WinDLL("winmm")

        u, k, a = self._user32, self._kernel32, self._advapi32
        u.SendInput.argtypes = [c_uint, POINTER(INPUT), c_int]
        u.SendInput.restype = c_uint
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = c_void_p
        u.GetWindowThreadProcessId.argtypes = [c_void_p, POINTER(c_uint32)]
        u.GetWindowThreadProcessId.restype = c_uint32
        u.GetAsyncKeyState.argtypes = [c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        k.OpenProcess.argtypes = [c_uint32, c_int, c_uint32]
        k.OpenProcess.restype = c_void_p
        k.CloseHandle.argtypes = [c_void_p]
        k.CloseHandle.restype = c_int
        k.GetCurrentProcessId.argtypes = []
        k.GetCurrentProcessId.restype = c_uint32
        a.OpenProcessToken.argtypes = [c_void_p, c_uint32, POINTER(c_void_p)]
        a.OpenProcessToken.restype = c_int

        self._pid = k.GetCurrentProcessId()
        self._admin = is_admin()
        self._struct_size = ctypes.sizeof(INPUT)

    # --------------------------------------------------------------- keys
    def _send(self, index: int, key_up: bool) -> None:
        event = build_key_event(index, key_up)
        sent = self._user32.SendInput(1, byref(event), self._struct_size)
        if sent != 1:
            raise KeyboardInputError(
                "SendInput failed (error %d)" % ctypes.get_last_error()
            )

    def key_down(self, index: int) -> None:
        self._send(index, False)

    def key_up(self, index: int) -> None:
        self._send(index, True)

    # ------------------------------------------------------- environment
    def foreground_state(self) -> str:
        """'self'    -> our own window has focus (don't type into ourselves)
        'blocked' -> focused window is probably elevated while we are not
        'ok'      -> keys should arrive normally
        """
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return "ok"
            pid = c_uint32(0)
            self._user32.GetWindowThreadProcessId(hwnd, byref(pid))
            if pid.value == self._pid:
                return "self"
            if self._admin:
                return "ok"  # elevated process can inject into anything
            return "blocked" if self._probably_elevated(pid.value) else "ok"
        except Exception:  # never let a status probe break the run loop
            return "ok"

    def _probably_elevated(self, pid: int) -> bool:
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not handle:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            token = c_void_p()
            if self._advapi32.OpenProcessToken(handle, TOKEN_QUERY, byref(token)):
                self._kernel32.CloseHandle(token)
                return False
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        finally:
            self._kernel32.CloseHandle(handle)

    def modifiers_down(self) -> bool:
        """True while the user physically holds Ctrl/Alt/Shift/Win."""
        for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN):
            if self._user32.GetAsyncKeyState(vk) & 0x8000:
                return True
        return False

    def begin_timer(self) -> None:
        try:  # 1 ms timer resolution -> accurate millisecond delays
            self._winmm.timeBeginPeriod(1)
        except Exception:
            pass

    def end_timer(self) -> None:
        try:
            self._winmm.timeEndPeriod(1)
        except Exception:
            pass


# --------------------------------------------------------------- process utils
def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_dpi_aware() -> None:
    """Crisp text on high-DPI screens (call before creating the Tk root)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def relaunch_as_admin() -> bool:
    """Start a new elevated copy of this app (shows the UAC prompt).

    Returns True if Windows launched it; False if the user declined UAC.
    """
    if not IS_WINDOWS:
        return False
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = [c_void_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
    shell32.ShellExecuteW.restype = c_void_p

    if getattr(sys, "frozen", False):  # packaged .exe
        exe, params = sys.executable, ""
        workdir = os.path.dirname(sys.executable)
    else:
        folder = os.path.dirname(os.path.abspath(sys.executable))
        pythonw = os.path.join(folder, "pythonw.exe")
        exe = pythonw if os.path.exists(pythonw) else sys.executable
        params = "-m fkeyautomator"
        workdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = shell32.ShellExecuteW(None, "runas", exe, params, workdir, 1)
    return (result or 0) > 32
