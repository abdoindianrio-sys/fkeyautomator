"""Local settings: load / validate / save as JSON.

The file lives in %APPDATA%\\FKeyAutomator\\settings.json on Windows.
Anything unreadable or out of range falls back to a safe default, so a
damaged file can never stop the app from starting.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

KEY_COUNT = 10  # F1 .. F10

DELAY_MIN, DELAY_MAX, DELAY_DEFAULT = 0, 3_600_000, 1000   # milliseconds
HOLD_MIN, HOLD_MAX, HOLD_DEFAULT = 10, 2000, 40             # milliseconds
START_MIN, START_MAX, START_DEFAULT = 0, 60, 3              # seconds

SCHEMA_VERSION = 5


def clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """Convert *value* to int and clamp it into [lo, hi]; fall back to *default*."""
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, number))


@dataclass
class KeyConfig:
    enabled: bool = False
    fixed_delay: bool = False
    fixed_delay_ms: int = DELAY_DEFAULT
    delay_min_ms: int = DELAY_DEFAULT
    delay_max_ms: int = DELAY_DEFAULT

    @property
    def delay_ms(self) -> int:
        """Compatibility with settings written before delay ranges existed."""
        return self.delay_min_ms

    @delay_ms.setter
    def delay_ms(self, value: int) -> None:
        self.delay_min_ms = self.delay_max_ms = value


@dataclass
class Settings:
    keys: List[KeyConfig] = field(
        default_factory=lambda: [KeyConfig() for _ in range(KEY_COUNT)]
    )
    start_delay_s: int = START_DEFAULT
    hold_ms: int = HOLD_DEFAULT
    window_x: Optional[int] = None
    window_y: Optional[int] = None
    theme: str = "dark"

    # ------------------------------------------------------------------ io
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "keys": [
                {
                    "enabled": bool(k.enabled),
                    "fixed_delay": bool(k.fixed_delay),
                    "fixed_delay_ms": int(k.fixed_delay_ms),
                    "delay_min_ms": int(k.delay_min_ms),
                    "delay_max_ms": int(k.delay_max_ms),
                }
                for k in self.keys
            ],
            "start_delay_s": int(self.start_delay_s),
            "hold_ms": int(self.hold_ms),
            "window": {"x": self.window_x, "y": self.window_y},
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        result = cls()
        if not isinstance(data, dict):
            return result

        raw_keys = data.get("keys")
        if isinstance(raw_keys, list):
            for i in range(KEY_COUNT):
                raw = raw_keys[i] if i < len(raw_keys) else None
                if isinstance(raw, dict):
                    enabled = raw.get("enabled", False)
                    # Older settings used one fixed delay. Keep that value as
                    # both ends of the range when migrating the file.
                    legacy_delay = raw.get("delay_ms", DELAY_DEFAULT)
                    delay_min = clamp_int(
                        raw.get("delay_min_ms", legacy_delay),
                        DELAY_MIN, DELAY_MAX, DELAY_DEFAULT
                    )
                    result.keys[i] = KeyConfig(
                        enabled=enabled if isinstance(enabled, bool) else False,
                        fixed_delay=(raw.get("fixed_delay", False)
                                     if isinstance(raw.get("fixed_delay", False), bool) else False),
                        fixed_delay_ms=clamp_int(
                            raw.get("fixed_delay_ms", delay_min),
                            DELAY_MIN, DELAY_MAX, DELAY_DEFAULT
                        ),
                        delay_min_ms=delay_min,
                        delay_max_ms=clamp_int(
                            raw.get("delay_max_ms", legacy_delay),
                            DELAY_MIN, DELAY_MAX, DELAY_DEFAULT
                        ),
                    )
                    if result.keys[i].delay_min_ms > result.keys[i].delay_max_ms:
                        result.keys[i].delay_min_ms, result.keys[i].delay_max_ms = (
                            result.keys[i].delay_max_ms, result.keys[i].delay_min_ms
                        )

        result.start_delay_s = clamp_int(
            data.get("start_delay_s"), START_MIN, START_MAX, START_DEFAULT
        )
        result.hold_ms = clamp_int(data.get("hold_ms"), HOLD_MIN, HOLD_MAX, HOLD_DEFAULT)
        theme = data.get("theme", "dark")
        result.theme = theme if theme in ("dark", "light") else "dark"

        window = data.get("window")
        if isinstance(window, dict):
            x, y = window.get("x"), window.get("y")
            if (
                isinstance(x, int) and not isinstance(x, bool)
                and isinstance(y, int) and not isinstance(y, bool)
            ):
                result.window_x, result.window_y = x, y
        return result


# ---------------------------------------------------------------- locations
def config_dir() -> str:
    override = os.environ.get("FKA_CONFIG_DIR")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "FKeyAutomator")


def default_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def load(path: Optional[str] = None) -> Settings:
    path = path or default_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return Settings.from_dict(json.load(fh))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as exc:  # unreadable or corrupt JSON
        log.warning("Could not read settings (%s); using defaults", exc)
        try:  # keep the damaged file for inspection instead of overwriting it silently
            os.replace(path, path + ".bad")
        except OSError:
            pass
        return Settings()


def save(settings: Settings, path: Optional[str] = None) -> bool:
    """Atomically write settings. Returns True on success."""
    path = path or default_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.error("Could not save settings: %s", exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
