"""Macro data model and validated JSON persistence."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from . import settings as cfg

log = logging.getLogger(__name__)

MACRO_SCHEMA = 1
MAX_MACROS = 100
MAX_EVENTS = 20_000
MAX_DELAY_MS = 3_600_000
MAX_REPEAT_COUNT = 1_000_000
DEFAULT_MACRO_HOTKEY = "Ctrl+Shift+F12"


@dataclass
class MacroEvent:
    """One physical input transition; delay_ms is from the previous event."""

    device: str
    code: str
    action: str
    delay_ms: int = 0
    scan_code: int = 0
    virtual_key: int = 0
    extended: bool = False
    x: int = 0
    y: int = 0

    def __post_init__(self) -> None:
        if self.device not in ("key", "mouse"):
            raise ValueError("invalid input device")
        if self.device == "mouse" and self.code == "move":
            if self.action != "move":
                raise ValueError("invalid mouse movement action")
            self.x = self._coordinate(self.x)
            self.y = self._coordinate(self.y)
        else:
            if self.action not in ("down", "up"):
                raise ValueError("invalid input action")
            if self.device == "mouse" and self.code not in ("left", "right", "middle", "x1", "x2"):
                raise ValueError("invalid mouse button")
            self.x = self._coordinate(self.x)
            self.y = self._coordinate(self.y)
        if self.device == "key":
            if not 0 <= int(self.scan_code) <= 0xFF or not 0 <= int(self.virtual_key) <= 0xFF:
                raise ValueError("invalid key code")
        self.delay_ms = cfg.clamp_int(self.delay_ms, 0, MAX_DELAY_MS, 0)
        self.scan_code = int(self.scan_code)
        self.virtual_key = int(self.virtual_key)
        self.extended = bool(self.extended)

    @staticmethod
    def _coordinate(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("invalid pointer coordinate")
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("invalid pointer coordinate")
        if result < -0x80000000 or result > 0x7FFFFFFF:
            raise ValueError("pointer coordinate is out of range")
        return result

    @property
    def identity(self) -> tuple:
        return (self.device, self.code, self.scan_code, self.virtual_key, self.extended)

    def key_up_copy(self) -> "MacroEvent":
        return MacroEvent(
            self.device, self.code, "up", 0, self.scan_code,
            self.virtual_key, self.extended,
        )

    @classmethod
    def from_dict(cls, raw: Any) -> "MacroEvent":
        if not isinstance(raw, dict):
            raise ValueError("event must be an object")
        return cls(
            device=str(raw.get("device", "")),
            code=str(raw.get("code", "")),
            action=str(raw.get("action", "")),
            delay_ms=raw.get("delay_ms", 0),
            scan_code=raw.get("scan_code", 0),
            virtual_key=raw.get("virtual_key", 0),
            extended=raw.get("extended", False),
            x=raw.get("x", 0),
            y=raw.get("y", 0),
        )


@dataclass
class Macro:
    id: str
    name: str
    events: List[MacroEvent] = field(default_factory=list)
    timing_mode: str = "recorded"  # recorded | fixed
    fixed_delay_ms: int = 100
    repeat_count: int = 1
    repeat_forever: bool = False

    def __post_init__(self) -> None:
        self.id = str(self.id)[:80]
        self.name = str(self.name).strip()[:80] or "ماكرو جديد"
        if self.timing_mode not in ("recorded", "fixed"):
            self.timing_mode = "recorded"
        self.fixed_delay_ms = cfg.clamp_int(self.fixed_delay_ms, 0, MAX_DELAY_MS, 100)
        self.repeat_count = cfg.clamp_int(self.repeat_count, 1, MAX_REPEAT_COUNT, 1)
        self.repeat_forever = self.repeat_forever if isinstance(self.repeat_forever, bool) else False

    @classmethod
    def from_dict(cls, raw: Any) -> "Macro":
        if not isinstance(raw, dict):
            raise ValueError("macro must be an object")
        macro_id = str(raw.get("id", ""))[:80]
        if not macro_id:
            raise ValueError("macro id is missing")
        raw_events = raw.get("events", [])
        if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
            raise ValueError("invalid macro event list")
        events = [MacroEvent.from_dict(item) for item in raw_events]
        return cls(
            id=macro_id,
            name=str(raw.get("name", "ماكرو جديد")),
            events=events,
            timing_mode=str(raw.get("timing_mode", "recorded")),
            fixed_delay_ms=raw.get("fixed_delay_ms", 100),
            repeat_count=raw.get("repeat_count", 1),
            repeat_forever=raw.get("repeat_forever", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "timing_mode": self.timing_mode,
            "fixed_delay_ms": self.fixed_delay_ms,
            "repeat_count": self.repeat_count,
            "repeat_forever": self.repeat_forever,
            "events": [asdict(event) for event in self.events],
        }


def macro_path() -> str:
    return os.path.join(cfg.config_dir(), "macros.json")


class MacroStore:
    """Stores macros separately from the existing settings.json file."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or macro_path()
        self.macros: List[Macro] = []
        self.hotkey = DEFAULT_MACRO_HOTKEY
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict) or raw.get("version") != MACRO_SCHEMA:
                raise ValueError("unsupported macro file version")
            items = raw.get("macros", [])
            if not isinstance(items, list) or len(items) > MAX_MACROS:
                raise ValueError("invalid macro list")
            self.macros = [Macro.from_dict(item) for item in items]
            ids = [macro.id for macro in self.macros]
            if any(not value for value in ids) or len(ids) != len(set(ids)):
                raise ValueError("macro ids must be unique")
            self.hotkey = normalize_hotkey(raw.get("hotkey", DEFAULT_MACRO_HOTKEY))
        except FileNotFoundError:
            self.macros = []
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Could not load macros (%s); using an empty list", exc)
            self.macros = []
            self.hotkey = DEFAULT_MACRO_HOTKEY

    def save(self) -> bool:
        if len(self.macros) > MAX_MACROS or any(len(macro.events) > MAX_EVENTS for macro in self.macros):
            log.error("Macro collection exceeds supported limits")
            return False
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            data = {
                "version": MACRO_SCHEMA,
                "hotkey": normalize_hotkey(self.hotkey),
                "macros": [macro.to_dict() for macro in self.macros],
            }
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            return True
        except OSError:
            log.exception("Could not save macros")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def export_macro(self, macro: Macro, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": MACRO_SCHEMA, "macro": macro.to_dict()}, fh,
                      ensure_ascii=False, indent=2)

    def import_macro(self, path: str) -> Macro:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or raw.get("version") != MACRO_SCHEMA:
            raise ValueError("ملف الماكرو غير مدعوم")
        macro = Macro.from_dict(raw.get("macro"))
        if any(old.id == macro.id for old in self.macros):
            import uuid
            macro.id = uuid.uuid4().hex
        if len(self.macros) >= MAX_MACROS:
            raise ValueError("وصلت للحد الأقصى لعدد الماكروز")
        return macro


def normalize_hotkey(value: Any) -> str:
    """Accept a constrained Ctrl/Alt/Shift chord ending in F1..F24 or A..Z."""
    if not isinstance(value, str):
        raise ValueError("invalid hotkey")
    parts = [part.strip().lower() for part in value.replace(" ", "").split("+")]
    aliases = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift"}
    if len(parts) < 2 or parts[-1] in aliases:
        raise ValueError("hotkey needs a modifier and a key")
    mods = []
    for part in parts[:-1]:
        if part not in aliases or aliases[part] in mods:
            raise ValueError("unsupported hotkey modifier")
        mods.append(aliases[part])
    key = parts[-1].upper()
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        pass
    elif len(key) == 1 and "A" <= key <= "Z":
        pass
    else:
        raise ValueError("unsupported hotkey key")
    order = [mod for mod in ("Ctrl", "Alt", "Shift") if mod in mods]
    return "+".join(order + [key])
