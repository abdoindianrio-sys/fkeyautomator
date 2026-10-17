"""Program entry point: wires the real Windows backend to the controller + window."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys

from . import settings as cfg


def _setup_logging() -> None:
    """pythonw.exe has no console, so write problems to a log file."""
    try:
        os.makedirs(cfg.config_dir(), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(cfg.config_dir(), "app.log"),
            maxBytes=200_000, backupCount=1, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _fatal(message: str) -> None:
    """Show an error even when there is no console (pythonw)."""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "FKey Automator", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    if sys.platform != "win32":
        print("FKey Automator works on Windows only.", file=sys.stderr)
        return 1
    _setup_logging()
    log = logging.getLogger("fkeyautomator")
    try:
        import tkinter  # noqa: F401  (fail early with a clear message)
    except ImportError:
        _fatal("Python's Tkinter is missing. Re-install Python and keep 'tcl/tk and IDLE' ticked.")
        return 1

    try:
        from .controller import Controller
        from .hotkey import GlobalHotkey
        from .keyboard_input import WindowsKeyboard, is_admin, relaunch_as_admin, set_dpi_aware
        from .macro_runtime import GlobalRecorder, WindowsMacroIO
        from .ui import MainWindow

        set_dpi_aware()
        controller = Controller(
            WindowsKeyboard(),
            hotkey_factory=GlobalHotkey,
            admin=is_admin(),
            relaunch=relaunch_as_admin,
            macro_recorder=GlobalRecorder(),
            macro_backend=WindowsMacroIO(),
            macro_hotkey_factory=GlobalHotkey,
        )
        MainWindow(controller).run()
        return 0
    except Exception as exc:
        log.exception("Fatal error")
        _fatal("FKey Automator crashed:\n%s\n\nDetails: %s" % (exc, os.path.join(cfg.config_dir(), "app.log")))
        return 1
