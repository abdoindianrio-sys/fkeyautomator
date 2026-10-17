# -*- coding: utf-8 -*-
"""The window. Thin view over controller.Controller.

Layout is right-to-left (Arabic): each key card keeps the shortcut visible
on its left edge and its status and delay controls grouped on the right.

Design idea: every F-key is drawn as a physical key cap.  When the engine
presses a key, its cap visibly "goes down" and lights up amber, so you can
see the sequence working without looking at the target window.
"""
from __future__ import annotations

import logging
import os
import sys
import tkinter as tk

from . import strings as T
from .controller import Controller
from .hotkey import HOTKEY_LABEL
from .keyboard_input import F_KEY_NAMES
from .settings import (
    DELAY_MAX, DELAY_MIN, KEY_COUNT,
)

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ palette
PALETTES = {
    "light": {
        "BG": "#F4F7FB", "SURFACE": "#FFFFFF", "RAISED": "#EEF2F7",
        "LINE": "#E3E9F1", "TEXT": "#182230", "MUTED": "#657386",
        "DIM": "#A4AFBD", "KEY_FACE": "#FFFFFF", "KEY_EDGE": "#D8E0EA",
        "KEY_INK": "#1C1D20", "PRESS": "#DCEBFF", "PRESS_EDGE": "#77AFFF",
        "ACCENT": "#1677F8", "GOOD": "#22A85A", "BAD": "#D94343",
        "STOP_BG": "#FFF0EF",
        "WARN": "#C77A08", "MIN_DELAY_COLOR": "#1677F8",
        "MAX_DELAY_COLOR": "#D97916", "MIN_INPUT_BG": "#F0F6FF",
        "MAX_INPUT_BG": "#FFF6EB",
    },
    "dark": {
        "BG": "#111A25", "SURFACE": "#192635", "RAISED": "#243749",
        "LINE": "#2B4053", "TEXT": "#E8F0F7", "MUTED": "#9BAEC0",
        "DIM": "#71869A", "KEY_FACE": "#203449", "KEY_EDGE": "#38566C",
        "KEY_INK": "#E8F0F7", "PRESS": "#1F3B50", "PRESS_EDGE": "#4B9BAD",
        "ACCENT": "#59B7C8", "GOOD": "#72C3A0", "BAD": "#D77986",
        "STOP_BG": "#382D37",
        "WARN": "#D8B77D", "MIN_DELAY_COLOR": "#72BDCC",
        "MAX_DELAY_COLOR": "#D4AA7C", "MIN_INPUT_BG": "#203548",
        "MAX_INPUT_BG": "#302F31",
    },
}


def system_theme() -> str:
    """Read Windows' app color preference; fall back cleanly on other systems."""
    if sys.platform != "win32":
        return "light"
    try:
        import winreg
        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                try:
                    return "light" if winreg.QueryValueEx(key, name)[0] else "dark"
                except OSError:
                    continue
    except (ImportError, OSError):
        pass
    return "light"


def apply_palette(theme: str) -> None:
    """Set the module palette before creating Tk widgets."""
    globals().update(PALETTES.get(theme, PALETTES["light"]))


def apply_windows_titlebar(root, theme: str) -> None:
    """Match the native Windows title bar to the selected app theme."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        value = ctypes.c_int(theme == "dark")
        hwnd = root.winfo_id()
        dwmapi = ctypes.windll.dwmapi
        for attribute in (20, 19):  # Windows 11, then the Windows 10 fallback.
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                return
    except (AttributeError, OSError, tk.TclError):
        log.debug("Could not set the native Windows title bar theme", exc_info=True)


apply_palette("light")

FONT_FAMILY = "Segoe UI"
_scale = 1.0


def px(value: float) -> int:
    """Scale a pixel size for the current display DPI."""
    return max(1, int(round(value * _scale)))


def font(size: int, weight: str = "normal"):
    return (FONT_FAMILY, size, weight)


def shade(color: str, factor: float) -> str:
    """Lighten (>1) or darken (<1) a #RRGGBB colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return "#%02X%02X%02X" % (r, g, b)


def rounded_rect(canvas, x1, y1, x2, y2, radius, **kw):
    pts = [
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ------------------------------------------------------------------ widgets
class Keycap(tk.Canvas):
    """A little 3-D key. Pressed = lit amber and pushed down."""

    def __init__(self, master, label: str, bg: str):
        self.w, self.h = px(56), px(36)
        super().__init__(master, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, bd=0)
        self.label = label
        self.pressed = False
        self.dim = False
        self.draw()

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)

    def set_state(self, pressed: bool, dim: bool) -> None:
        if pressed != self.pressed or dim != self.dim:
            self.pressed, self.dim = pressed, dim
            self.draw()

    def draw(self) -> None:
        self.delete("all")
        if self.pressed:
            face, edge, ink = PRESS, PRESS_EDGE, KEY_INK
        elif self.dim:
            face, edge, ink = RAISED, LINE, DIM
        else:
            face, edge, ink = KEY_FACE, KEY_EDGE, KEY_INK
        rounded_rect(self, 1, 1, self.w - 1, self.h - 1, px(10),
                     fill=face, outline=edge, width=1)
        self.create_text(self.w / 2, self.h / 2, text=self.label,
                         fill=ACCENT if self.pressed else ink, font=font(11, "bold"))


class Toggle(tk.Canvas):
    """Pill switch bound to a BooleanVar. Keyboard: Space / Enter."""

    def __init__(self, master, variable: tk.BooleanVar, command, bg: str):
        self.w, self.h = px(44), px(24)
        super().__init__(master, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.var, self.command, self.focused = variable, command, False
        self.bind("<Button-1>", self._click)
        self.bind("<space>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        variable.trace_add("write", lambda *a: self.draw())
        self.draw()

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)

    def _focus(self, focused: bool) -> None:
        self.focused = focused
        self.draw()

    def _click(self, _event=None) -> None:
        self.var.set(not self.var.get())
        self.command()

    def draw(self) -> None:
        self.delete("all")
        on = bool(self.var.get())
        color = ACCENT if on else LINE
        ring = TEXT if self.focused else color
        h, w = self.h, self.w
        self.create_oval(1, 1, h - 1, h - 1, fill=color, outline=ring)
        self.create_oval(w - h + 1, 1, w - 1, h - 1, fill=color, outline=ring)
        self.create_rectangle(h / 2, 1, w - h / 2, h - 1, fill=color, outline=color)
        self.create_line(h / 2, 1, w - h / 2, 1, fill=ring)
        self.create_line(h / 2, h - 1, w - h / 2, h - 1, fill=ring)
        pad = px(4)
        x = (w - h + pad) if on else pad
        self.create_oval(x, pad, x + h - 2 * pad, h - pad, fill=TEXT, outline=TEXT)


class Stepper(tk.Frame):
    """[ - ]  value  [ + ] with digits-only entry, clamped to [lo, hi]."""

    def __init__(self, master, value: int, lo: int, hi: int, step: int, on_change, bg: str,
                 entry_chars: int = 7, entry_bg: str = BG, accent: str = ACCENT):
        super().__init__(master, bg=bg)
        self.lo, self.hi, self.step, self.on_change = lo, hi, step, on_change
        self._disabled = False
        self._value = max(lo, min(hi, int(value)))
        self.var = tk.StringVar(value=str(self._value))

        self.minus = self._button("−", -1)
        self.entry = tk.Entry(
            self, textvariable=self.var, width=entry_chars, justify="center",
            font=font(10), relief="flat", bd=0, bg=entry_bg, fg=TEXT, insertbackground=TEXT,
            selectbackground=ACCENT, selectforeground=KEY_INK,
            disabledforeground=DIM,
            highlightthickness=1, highlightbackground=LINE, highlightcolor=accent,
            validate="key", validatecommand=(self.register(self._validate), "%P"),
        )
        self.plus = self._button("+", +1)
        self.minus.pack(side="left")
        self.entry.pack(side="left", padx=px(4), ipady=px(3))
        self.plus.pack(side="left")

        self.var.trace_add("write", self._typed)
        self.entry.bind("<FocusOut>", self._commit)
        self.entry.bind("<Return>", self._commit)
        self.entry.bind("<Up>", lambda e: self._bump(+1))
        self.entry.bind("<Down>", lambda e: self._bump(-1))

    def _button(self, text: str, direction: int) -> tk.Label:
        label = tk.Label(self, text=text, width=2, font=font(12, "bold"), bg=RAISED, fg=TEXT,
                         cursor="hand2", padx=px(1), pady=px(1))
        label.bind("<Button-1>", lambda e: self._bump(direction))
        label.bind("<Enter>", lambda e: label.configure(
            bg=SURFACE if self._disabled else shade(RAISED, 1.25)
        ))
        label.bind("<Leave>", lambda e: label.configure(
            bg=SURFACE if self._disabled else RAISED
        ))
        return label

    @property
    def value(self) -> int:
        return self._value

    def _validate(self, proposed: str) -> bool:
        return proposed == "" or (proposed.isdigit() and len(proposed) <= len(str(self.hi)))

    def _typed(self, *_args) -> None:
        text = self.var.get()
        if text.isdigit():
            self._set_value(max(self.lo, min(self.hi, int(text))))

    def _commit(self, _event=None) -> None:
        self.var.set(str(self._value))  # show the clamped / last valid value

    def _bump(self, direction: int):
        if self._disabled:
            return "break"
        self._set_value(max(self.lo, min(self.hi, self._value + direction * self.step)))
        self.var.set(str(self._value))
        return "break"

    def _set_value(self, value: int) -> None:
        if value != self._value:
            self._value = value
            self.on_change(value)

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)

    def set_dim(self, dim: bool, disabled: bool = False) -> None:
        self._disabled = disabled
        color = DIM if dim else TEXT
        self.entry.configure(fg=color, state="disabled" if disabled else "normal")
        button_bg = SURFACE if dim or disabled else RAISED
        button_cursor = "arrow" if disabled else "hand2"
        self.minus.configure(fg=color, bg=button_bg, cursor=button_cursor)
        self.plus.configure(fg=color, bg=button_bg, cursor=button_cursor)

    def set_value(self, value: int) -> None:
        """Update the displayed value when the paired range endpoint moves."""
        value = max(self.lo, min(self.hi, int(value)))
        if value != self._value:
            self._value = value
            self.var.set(str(value))


class FlatButton(tk.Label):
    def __init__(self, master, text: str, command, color: str, ink: str, parent_bg: str = BG):
        super().__init__(master, text=text, font=font(13, "bold"), bg=color, fg=ink,
                         pady=px(9), cursor="hand2", takefocus=1,
                         highlightthickness=2, highlightbackground=parent_bg,
                         highlightcolor=TEXT)
        self.command, self.color, self.ink, self.parent_bg, self.enabled = command, color, ink, parent_bg, True
        self.bind("<Enter>", lambda e: self._paint(hover=True))
        self.bind("<Leave>", lambda e: self._paint())
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda e: self._fire())
        self.bind("<space>", lambda e: self._fire())

    def _paint(self, hover: bool = False) -> None:
        if self.enabled:
            self.configure(bg=shade(self.color, 1.12) if hover else self.color, fg=self.ink,
                           cursor="hand2")
        else:
            self.configure(bg=RAISED, fg=DIM, cursor="arrow")

    def _release(self, event) -> None:
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._fire()

    def _fire(self) -> None:
        if self.enabled:
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        if enabled != self.enabled:
            self.enabled = enabled
            self._paint()


# ---------------------------------------------------------------------- rows
class KeyRow:
    """One F-key with enable, fixed-delay mode, and delay controls."""

    def __init__(self, parent, controller: Controller, index: int):
        self.c, self.index = controller, index
        key_cfg = controller.settings.keys[index]
        self.frame = tk.Canvas(parent, bg=BG, height=px(122), highlightthickness=0, bd=0)
        self.card = tk.Frame(self.frame, bg=SURFACE)
        self._card_shape = rounded_rect(
            self.frame, 2, 2, px(410), px(118), px(13), fill=SURFACE,
            outline=LINE, width=1,
        )
        self._card_window = self.frame.create_window(
            px(6), px(6), anchor="nw", window=self.card, width=px(390)
        )
        self.frame.bind("<Configure>", self._resize_card)
        # A restrained edge marker carries the HUD reference through without
        # relying on bright glow effects; its color follows the key state.
        self.edge_mark = tk.Frame(self.card, bg=LINE, width=px(3), height=px(22))
        self.edge_mark.pack(side="left", padx=(px(1), px(5)), pady=px(40))
        head = tk.Frame(self.card, bg=SURFACE)
        head.pack(fill="x", padx=px(14), pady=(px(7), px(4)))
        identity = tk.Frame(head, bg=SURFACE)
        identity.pack(side="left")
        self.keycap = Keycap(identity, F_KEY_NAMES[index], SURFACE)
        self.keycap.pack(side="left", padx=(0, px(8)))
        self.keycap.configure(cursor="hand2")
        self.keycap.bind("<ButtonRelease-1>", lambda _event: self._toggle_enabled())
        self.enabled_var = tk.BooleanVar(value=key_cfg.enabled)
        self.toggle = Toggle(head, self.enabled_var, self._on_toggle, SURFACE)
        self.toggle.pack(side="right", padx=(0, px(7)))
        self.enabled_text = tk.Label(head, text="", font=font(9, "bold"),
                                     bg=SURFACE, fg=MUTED)
        self.enabled_text.pack(side="right")
        self.enabled_text.configure(cursor="hand2")
        self.enabled_text.bind("<ButtonRelease-1>", lambda _event: self._toggle_enabled())

        tk.Frame(self.card, bg=LINE, height=1).pack(fill="x", padx=px(14))
        controls = tk.Frame(self.card, bg=SURFACE)
        controls.pack(fill="x", padx=px(14), pady=(px(5), px(6)))
        mode = tk.Frame(controls, bg=SURFACE)
        mode.pack(fill="x", pady=(0, px(4)))
        self.fixed_var = tk.BooleanVar(value=key_cfg.fixed_delay)
        self.fixed_toggle = Toggle(mode, self.fixed_var, self._on_fixed_toggle, SURFACE)
        self.fixed_toggle.pack(side="right")
        self.fixed_label = tk.Label(mode, text=T.MODE_FIXED, font=font(9, "bold"),
                                    bg=SURFACE, fg=MUTED)
        self.fixed_label.pack(side="right", padx=(px(6), 0))
        self.fixed_label.configure(cursor="hand2")
        self.fixed_label.bind("<ButtonRelease-1>", lambda _event: self._toggle_fixed())
        tk.Label(mode, text=T.COL_DELAY, font=font(9), bg=SURFACE, fg=MUTED).pack(side="left")

        delay = tk.Frame(controls, bg=SURFACE)
        delay.pack(fill="x")
        self.min_label = tk.Label(delay, text="من", font=font(9, "bold"),
                                  bg=SURFACE, fg=MIN_DELAY_COLOR)
        self.max_label = tk.Label(delay, text="إلى", font=font(9, "bold"),
                                  bg=SURFACE, fg=MAX_DELAY_COLOR)
        self.min_stepper = Stepper(
            delay,
            key_cfg.fixed_delay_ms if key_cfg.fixed_delay else key_cfg.delay_min_ms,
            DELAY_MIN, DELAY_MAX, 100,
            self._set_min, SURFACE, entry_chars=6, entry_bg=MIN_INPUT_BG,
            accent=MIN_DELAY_COLOR,
        )
        self.max_stepper = Stepper(
            delay, key_cfg.delay_max_ms, DELAY_MIN, DELAY_MAX, 100,
            self._set_max, SURFACE, entry_chars=6, entry_bg=MAX_INPUT_BG,
            accent=MAX_DELAY_COLOR,
        )
        # Alias retained for clients that used the former single-delay row.
        self.stepper = self.min_stepper

        self.min_label.pack(side="right", padx=(0, px(4)))
        self.min_stepper.pack(side="right", padx=(0, px(7)))
        tk.Label(delay, text="–", font=font(10, "bold"), bg=SURFACE, fg=MUTED).pack(
            side="right", padx=px(4)
        )
        self.max_label.pack(side="right", padx=(px(4), 0))
        self.max_stepper.pack(side="right", padx=(px(7), 0))
        self.refresh(pressed=False)

    def _resize_card(self, event) -> None:
        inset = px(8)
        self.frame.itemconfigure(self._card_window, width=max(1, event.width - 2 * inset))
        x1, y1, x2, y2 = 2, 2, event.width - 2, event.height - 2
        radius = px(14)
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        self.frame.coords(self._card_shape, *points)

    def _toggle_enabled(self) -> None:
        self.enabled_var.set(not self.enabled_var.get())
        self._on_toggle()

    def _toggle_fixed(self) -> None:
        self.fixed_var.set(not self.fixed_var.get())
        self._on_fixed_toggle()

    def _on_toggle(self) -> None:
        self.c.set_enabled(self.index, self.enabled_var.get())
        self.refresh(pressed=self.c.state.active_key == self.index)

    def _on_fixed_toggle(self) -> None:
        fixed = self.fixed_var.get()
        self.c.set_fixed_delay(self.index, fixed)
        key_cfg = self.c.settings.keys[self.index]
        self.min_stepper.set_value(
            key_cfg.fixed_delay_ms if fixed else key_cfg.delay_min_ms
        )
        self.refresh(pressed=self.c.state.active_key == self.index)

    def _set_min(self, value: int) -> None:
        if self.fixed_var.get():
            self.c.set_fixed_delay_ms(self.index, value)
        else:
            self.c.set_delay_min(self.index, value)
            self.max_stepper.set_value(self.c.settings.keys[self.index].delay_max_ms)

    def _set_max(self, value: int) -> None:
        self.c.set_delay_max(self.index, value)
        self.min_stepper.set_value(self.c.settings.keys[self.index].delay_min_ms)

    def refresh(self, pressed: bool) -> None:
        enabled = self.enabled_var.get()
        outline = PRESS_EDGE if pressed else (ACCENT if enabled else LINE)
        self.frame.itemconfigure(self._card_shape, outline=outline)
        self.edge_mark.configure(bg=PRESS_EDGE if pressed else (ACCENT if enabled else LINE))
        self.keycap.set_state(pressed, dim=not enabled)
        self.enabled_text.configure(text="مفعّل" if enabled else "متوقف",
                                    fg=GOOD if enabled else MUTED)
        fixed = self.fixed_var.get()
        dim_min = not enabled
        dim_max = not enabled or fixed
        self.min_label.configure(
            text=T.DELAY_FIXED if fixed else "من",
            fg=DIM if dim_min else MIN_DELAY_COLOR,
        )
        self.max_label.configure(fg=DIM if dim_max else MAX_DELAY_COLOR)
        self.min_stepper.set_dim(dim_min)
        self.max_stepper.set_dim(dim_max, disabled=fixed)


# ------------------------------------------------------------------- window
class MainWindow:
    POLL_MS = 25

    def __init__(self, controller: Controller):
        global _scale
        self.c = controller
        self.theme = controller.settings.theme
        apply_palette(self.theme)
        self.root = tk.Tk()
        self.mini_bar = None
        self.macro_window = None
        self.recorder_window = None
        try:
            _scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except (tk.TclError, ValueError):
            _scale = 1.0

        root = self.root
        root.title(T.APP_TITLE)
        root.configure(bg=BG)
        root.resizable(True, True)
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app.ico")
        try:
            root.iconbitmap(icon)
        except tk.TclError:
            pass  # icon is optional
        apply_windows_titlebar(root, self.theme)

        # pythonw has no console: send errors raised inside Tk callbacks to the log file.
        root.report_callback_exception = lambda *exc: log.error("Tk callback error", exc_info=exc)

        self.rows = []
        self._build()
        root.update_idletasks()
        root.minsize(px(900), px(630))
        self._place_window()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.render()

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        root, c = self.root, self.c
        tk.Frame(root, bg=BG, width=px(900), height=1).pack()  # sets a compact starting width

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=px(24), pady=(px(18), px(8)))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="right")
        tk.Label(titles, text=T.APP_TITLE, font=font(21, "bold"), bg=BG, fg=TEXT).pack(anchor="e")
        tk.Label(titles, text=T.APP_SUBTITLE, font=font(10), bg=BG, fg=MUTED).pack(anchor="e")
        mark = tk.Label(header, text="F", font=font(16, "bold"), bg=ACCENT, fg="#FFFFFF",
                        width=2, height=1, padx=px(3), pady=px(2))
        mark.pack(side="right", padx=(px(12), 0))
        self.minimize_btn = FlatButton(
            header, "−  " + T.BTN_MINIMIZE, self._on_minimize, RAISED, TEXT, BG
        )
        self.minimize_btn.pack(side="left", anchor="n", padx=(0, px(8)), pady=px(2))
        self.macros_btn = FlatButton(
            header, "مكتبة الماكروز", self._on_macros, RAISED, TEXT, BG
        )
        self.macros_btn.pack(side="left", anchor="n", padx=(0, px(8)), pady=px(2))
        self.recorder_btn = FlatButton(
            header, "●  " + T.BTN_RECORDER, self._on_recorder, ACCENT, "#FFFFFF", BG
        )
        self.recorder_btn.pack(side="left", anchor="n", padx=(0, px(8)), pady=px(2))
        self.theme_btn = FlatButton(
            header, T.BTN_THEME_LIGHT if self.theme == "dark" else T.BTN_THEME_DARK,
            self._toggle_theme, RAISED, TEXT, BG,
        )
        self.theme_btn.pack(side="left", anchor="n", padx=(0, px(8)), pady=px(2))
        self.pill = tk.Label(header, text="", font=font(10, "bold"), padx=px(12), pady=px(5),
                             bg=LINE, fg=TEXT)
        self.pill.pack(side="left", anchor="n", pady=px(4))

        section = tk.Frame(root, bg=BG)
        section.pack(fill="x", padx=px(24), pady=(px(4), px(8)))
        tk.Label(section, text="تشغيل مفاتيح F1–F10", font=font(17, "bold"), bg=BG, fg=TEXT).pack(side="right")
        tk.Label(section, text="اضغط على زر F أو المفتاح لتبديل التفعيل", font=font(10),
                 bg=BG, fg=MUTED).pack(side="right", padx=(px(10), 0), pady=(px(3), 0))

        # Fixed one-line slot keeps the key grid in place when messages appear.
        self.message = tk.Label(root, text="", font=font(9), bg=BG, fg=WARN, anchor="e",
                                justify="right", wraplength=px(900), height=1)
        self.message.pack(fill="x", padx=px(24), pady=(0, px(4)))

        scroll_area = tk.Frame(root, bg=BG)
        scroll_area.pack(fill="both", expand=True, padx=px(19), pady=(0, px(8)))
        self.key_canvas = tk.Canvas(
            scroll_area, bg=BG, highlightthickness=0, bd=0, height=px(350)
        )
        self.key_scrollbar = tk.Scrollbar(
            scroll_area, orient="vertical", command=self.key_canvas.yview,
            width=px(12), bg=RAISED, troughcolor=BG, activebackground=ACCENT,
            bd=0, relief="flat", highlightthickness=0,
        )
        self.key_scrollbar.pack(side="right", fill="y", padx=(px(5), 0))
        self.key_canvas.pack(side="left", fill="both", expand=True)
        self.key_canvas.configure(yscrollcommand=self.key_scrollbar.set)
        grid = tk.Frame(self.key_canvas, bg=BG)
        self.key_grid_window = self.key_canvas.create_window(
            (0, 0), window=grid, anchor="nw"
        )
        grid.bind("<Configure>", self._update_scroll_region)
        self.key_canvas.bind("<Configure>", self._resize_key_grid)
        grid.grid_columnconfigure(0, weight=1, uniform="keycards")
        grid.grid_columnconfigure(1, weight=1, uniform="keycards")
        for i in range(KEY_COUNT):
            row = KeyRow(grid, c, i)
            row.frame.grid(row=i // 2, column=i % 2, sticky="ew",
                           padx=px(5), pady=px(4))
            self.rows.append(row)
        self._bind_scroll_wheel(grid)

        actions = tk.Frame(root, bg=BG)
        actions.pack(fill="x", padx=px(24), pady=(0, px(8)))
        self.start_btn = FlatButton(actions, T.BTN_START, self._on_start, ACCENT, "#FFFFFF",
                                    parent_bg=BG)
        self.start_btn.pack(side="right", expand=True, fill="x", padx=(px(6), 0))
        self.stop_btn = FlatButton(actions, T.BTN_STOP, self._on_stop, STOP_BG, BAD,
                                   parent_bg=BG)
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(0, px(6)))

        hint = tk.Frame(root, bg=BG)
        hint.pack(fill="x", padx=px(24), pady=(px(2), px(6)))
        tk.Label(hint, text=T.HOTKEY_HINT, font=font(9), bg=BG, fg=MUTED).pack(side="right")
        self.hotkey_chip = tk.Label(hint, text=HOTKEY_LABEL, font=("Consolas", 9), bg=RAISED,
                                    fg=TEXT, padx=px(8), pady=px(2))
        self.hotkey_chip.pack(side="right", padx=px(8))

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", padx=px(24), pady=(px(2), px(14)))
        self.stats = tk.Label(footer, text="", font=font(9), bg=BG, fg=MUTED)
        self.stats.pack(side="right")
        if c.admin:
            tk.Label(footer, text=T.ADMIN_ON, font=font(9), bg=BG, fg=GOOD).pack(side="left")
        else:
            link = tk.Label(footer, text=T.ADMIN_RESTART, font=(FONT_FAMILY, 9, "underline"),
                            bg=BG, fg=ACCENT, cursor="hand2")
            link.pack(side="left")
            link.bind("<Button-1>", lambda e: self._on_admin())

    def _update_scroll_region(self, _event=None) -> None:
        bounds = self.key_canvas.bbox("all")
        if bounds:
            self.key_canvas.configure(scrollregion=bounds)

    def _resize_key_grid(self, event) -> None:
        self.key_canvas.itemconfigure(self.key_grid_window, width=event.width)
        self._update_scroll_region()

    def _bind_scroll_wheel(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_scroll_wheel)
        for child in widget.winfo_children():
            self._bind_scroll_wheel(child)

    def _on_scroll_wheel(self, event):
        units = int(-event.delta / 120)
        if units:
            self.key_canvas.yview_scroll(units, "units")
        return "break"

    def _place_window(self) -> None:
        root, s = self.root, self.c.settings
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = s.window_x, s.window_y
        if x is None or y is None or not (-w + 80 < x < sw - 80) or not (0 <= y < sh - 80):
            x, y = (sw - w) // 2, max(0, (sh - h) // 3)
        root.geometry("+%d+%d" % (x, y))

    # ------------------------------------------------------------- drawing
    def render(self) -> None:
        st = self.c.state

        if st.macro_recording:
            text, bg, fg = "جاري تسجيل ماكرو", BAD, "#FFFFFF"
        elif st.macro_playing:
            text, bg, fg = "جاري تشغيل ماكرو", ACCENT, "#FFFFFF"
        elif st.phase == "countdown":
            text, bg, fg = T.STATUS["countdown"].format(n=st.countdown), WARN, KEY_INK
        elif st.phase == "waiting":
            text, bg, fg = T.STATUS["waiting"], WARN, KEY_INK
        elif st.phase == "running":
            text, bg, fg = T.STATUS["running"], GOOD, KEY_INK
        elif st.phase == "error":
            text, bg, fg = T.STATUS["error"], BAD, KEY_INK
        elif st.phase == "stopped":
            text, bg, fg = T.STATUS["stopped"], LINE, TEXT
        else:
            text, bg, fg = T.STATUS["ready"], LINE, TEXT
        self.pill.configure(text=text, bg=bg, fg=fg)

        if st.message_key:
            color = {"error": BAD, "warn": WARN}.get(st.message_kind, ACCENT)
            self.message.configure(
                text=T.MESSAGES[st.message_key].format(detail=st.message_detail), fg=color)
        else:
            self.message.configure(text="")

        for row in self.rows:
            row.refresh(pressed=(st.active_key == row.index))

        self.start_btn.set_enabled(not st.running and not st.macro_recording and not st.macro_playing)
        self.stop_btn.set_enabled(st.running or st.macro_recording or st.macro_playing)
        self.stats.configure(text=T.STATS.format(presses=st.presses, cycles=st.cycles))
        self.hotkey_chip.configure(fg=DIM if st.hotkey_ok is False else TEXT)
        self._render_mini_bar()
        self._render_macro_window()
        self._render_recorder_window()

    # ------------------------------------------------------------- actions
    def _on_start(self) -> None:
        self.c.start()
        self.render()

    def _on_minimize(self) -> None:
        if self.mini_bar is not None and self.mini_bar.winfo_exists():
            self.mini_bar.lift()
            return

        # Remember the full window position before withdrawing it; withdrawn
        # windows report sentinel coordinates on Windows.
        self.c.settings.window_x = self.root.winfo_x()
        self.c.settings.window_y = self.root.winfo_y()
        bar = tk.Toplevel(self.root)
        self.mini_bar = bar
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(bg=LINE)
        bar.bind("<Escape>", lambda _event: self._restore_window())

        shell = tk.Frame(bar, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        handle = tk.Frame(shell, bg=SURFACE, cursor="fleur")
        handle.pack(side="right", fill="y", padx=(px(10), px(6)), pady=px(7))
        tk.Label(handle, text="F", font=font(10, "bold"), bg=ACCENT, fg="#FFFFFF",
                 width=2, pady=px(2)).pack(side="right", padx=(0, px(7)))
        self.mini_status = tk.Label(handle, text="", font=font(9, "bold"),
                                    bg=SURFACE, fg=TEXT)
        self.mini_status.pack(side="right")
        handle.bind("<ButtonPress-1>", self._mini_drag_start)
        handle.bind("<B1-Motion>", self._mini_drag_move)
        for child in handle.winfo_children():
            child.bind("<ButtonPress-1>", self._mini_drag_start)
            child.bind("<B1-Motion>", self._mini_drag_move)

        self.mini_action = tk.Label(shell, text="", font=font(9, "bold"),
                                    padx=px(12), pady=px(6), cursor="hand2")
        self.mini_action.pack(side="right", padx=px(4), pady=px(5))
        self.mini_action.bind("<ButtonRelease-1>", lambda _event: self._on_mini_toggle())
        restore = tk.Label(shell, text="↗", font=font(12, "bold"), bg=RAISED, fg=TEXT,
                           width=3, pady=px(3), cursor="hand2")
        restore.pack(side="right", padx=px(3), pady=px(5))
        restore.bind("<ButtonRelease-1>", lambda _event: self._restore_window())
        close = tk.Label(shell, text="×", font=font(14), bg=SURFACE, fg=MUTED,
                         width=2, cursor="hand2")
        close.pack(side="left", padx=(px(5), px(2)))
        close.bind("<ButtonRelease-1>", lambda _event: self._on_close())

        bar.update_idletasks()
        width, height = bar.winfo_reqwidth(), bar.winfo_reqheight()
        x = max(0, (bar.winfo_screenwidth() - width) // 2)
        bar.geometry(f"{width}x{height}+{x}+{px(12)}")
        self.root.withdraw()
        self._render_mini_bar()

    def _mini_drag_start(self, event) -> None:
        if self.mini_bar is not None:
            self._mini_drag_offset = (event.x_root - self.mini_bar.winfo_x(),
                                      event.y_root - self.mini_bar.winfo_y())

    def _mini_drag_move(self, event) -> None:
        if self.mini_bar is not None and hasattr(self, "_mini_drag_offset"):
            x = event.x_root - self._mini_drag_offset[0]
            y = event.y_root - self._mini_drag_offset[1]
            self.mini_bar.geometry(f"+{x}+{max(0, y)}")

    def _render_mini_bar(self) -> None:
        bar = self.mini_bar
        if bar is None or not bar.winfo_exists():
            return
        st = self.c.state
        if st.macro_recording:
            status, color = "تسجيل ماكرو", BAD
        elif st.macro_playing:
            status, color = "تشغيل ماكرو", GOOD
        elif st.phase == "countdown":
            status, color = T.STATUS["countdown"].format(n=st.countdown), WARN
        elif st.phase == "waiting":
            status, color = T.STATUS["waiting"], WARN
        elif st.phase == "running":
            status, color = T.STATUS["running"], GOOD
        elif st.phase == "error":
            status, color = T.STATUS["error"], BAD
        elif st.phase == "stopped":
            status, color = T.STATUS["stopped"], MUTED
        else:
            status, color = T.STATUS["ready"], MUTED
        self.mini_status.configure(text=status, fg=color)
        self.mini_action.configure(
            text=T.BTN_STOP if (st.running or st.macro_recording or st.macro_playing) else T.BTN_START,
            bg=STOP_BG if (st.running or st.macro_recording or st.macro_playing) else ACCENT,
            fg=BAD if (st.running or st.macro_recording or st.macro_playing) else "#FFFFFF",
        )

    def _on_mini_toggle(self) -> None:
        if self.c.state.running or self.c.state.macro_recording or self.c.state.macro_playing:
            self._on_stop()
        else:
            self._on_start()
        self.render()

    def _restore_window(self) -> None:
        if self.mini_bar is not None:
            try:
                self.mini_bar.destroy()
            except tk.TclError:
                pass
            self.mini_bar = None
        self.root.deiconify()
        self.root.lift()

    def _on_stop(self) -> None:
        if self.c.state.macro_recording:
            self.c.stop_recording()
        elif self.c.state.macro_playing:
            self.c.stop_macro()
        else:
            self.c.stop()

    # --------------------------------------------------------- macro manager
    def _on_macros(self) -> None:
        if getattr(self, "macro_window", None) is not None:
            try:
                if self.macro_window.winfo_exists():
                    self.macro_window.deiconify()
                    self.macro_window.lift()
                    return
            except tk.TclError:
                pass
        self._build_macro_window()

    def _on_recorder(self) -> None:
        if self.recorder_window is not None:
            try:
                if self.recorder_window.winfo_exists():
                    self.recorder_window.deiconify()
                    self.recorder_window.lift()
                    self.recorder_window.focus_set()
                    return
            except tk.TclError:
                pass
        self._build_recorder_window()

    def _toggle_theme(self) -> None:
        old_theme = self.theme
        new_theme = "light" if old_theme == "dark" else "dark"
        old_palette = PALETTES[old_theme]
        new_palette = PALETTES[new_theme]
        self.theme = new_theme
        self.c.settings.theme = new_theme
        apply_palette(new_theme)
        self.c.save_now()
        self.theme_btn.configure(
            text=T.BTN_THEME_LIGHT if new_theme == "dark" else T.BTN_THEME_DARK,
            bg=RAISED, fg=TEXT,
        )
        self.theme_btn.color, self.theme_btn.ink = RAISED, TEXT
        windows = [self.root, self.macro_window, self.recorder_window, self.mini_bar]
        for window in windows:
            if window is not None:
                self._recolor_widget(window, old_palette, new_palette)
                apply_windows_titlebar(window, new_theme)
        for row in self.rows:
            row.frame.itemconfigure(row._card_shape, fill=SURFACE)
            row.keycap.draw()
            row.toggle.draw()
            row.fixed_toggle.draw()
            row.refresh(pressed=self.c.state.active_key == row.index)
        self._configure_macro_tree_style()
        self.render()

    def _recolor_widget(self, widget, old_palette, new_palette) -> None:
        reverse = {}
        for name, value in old_palette.items():
            reverse.setdefault(value, new_palette.get(name, value))
        options = (
            "bg", "fg", "highlightbackground", "highlightcolor", "insertbackground",
            "selectbackground", "selectforeground", "disabledforeground", "troughcolor",
            "activebackground", "activeforeground", "fieldbackground",
        )
        changes = {}
        for option in options:
            try:
                current = widget.cget(option)
                if current in reverse:
                    changes[option] = reverse[current]
            except (tk.TclError, TypeError, KeyError):
                pass
        try:
            if changes:
                widget.configure(**changes)
            if isinstance(widget, FlatButton):
                widget.color = reverse.get(widget.color, widget.color)
                widget.ink = reverse.get(widget.ink, widget.ink)
                widget.parent_bg = reverse.get(widget.parent_bg, widget.parent_bg)
                widget.configure(highlightbackground=widget.parent_bg, highlightcolor=TEXT)
                widget._paint()
            elif isinstance(widget, Toggle):
                widget.draw()
        except tk.TclError:
            pass
        try:
            children = widget.winfo_children()
        except (tk.TclError, AttributeError):
            children = []
        for child in children:
            self._recolor_widget(child, old_palette, new_palette)

    def _build_macro_window(self) -> None:
        from tkinter import filedialog, messagebox, simpledialog, ttk

        self._macro_filedialog = filedialog
        self._macro_messagebox = messagebox
        self._macro_simpledialog = simpledialog
        win = tk.Toplevel(self.root)
        self.macro_window = win
        win.title("مكتبة الماكروز")
        win.configure(bg=BG)
        win.geometry("1000x640")
        win.minsize(820, 500)
        apply_windows_titlebar(win, self.theme)
        win.protocol("WM_DELETE_WINDOW", self._close_macro_window)

        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Macro.Treeview", background=SURFACE, fieldbackground=SURFACE,
                        foreground=TEXT, rowheight=px(28), borderwidth=0)
        style.configure("Macro.Treeview.Heading", background=RAISED, foreground=TEXT,
                        relief="flat", font=font(9, "bold"))
        style.map("Macro.Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#FFFFFF")])

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=px(18), pady=(px(14), px(8)))
        tk.Label(top, text="مكتبة الماكروز", font=font(18, "bold"), bg=BG, fg=TEXT).pack(side="right")
        self.macro_status = tk.Label(top, text="", font=font(10, "bold"), bg=BG, fg=GOOD)
        self.macro_status.pack(side="right", padx=px(14))
        FlatButton(top, "●  فتح مسجل الإجراءات", self._on_recorder, ACCENT, "#FFFFFF", BG).pack(
            side="left", padx=px(4))

        hotkey_row = tk.Frame(win, bg=BG)
        hotkey_row.pack(fill="x", padx=px(18), pady=(0, px(9)))
        tk.Label(hotkey_row, text="اختصار تشغيل الماكرو", font=font(9), bg=BG, fg=MUTED).pack(side="right")
        self.macro_hotkey_var = tk.StringVar(value=self.c.macro_store.hotkey)
        self.macro_hotkey_entry = tk.Entry(
            hotkey_row, textvariable=self.macro_hotkey_var, width=20, justify="center",
            font=font(10), bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        self.macro_hotkey_entry.pack(side="right", padx=px(8), ipady=px(4))
        FlatButton(hotkey_row, "تطبيق الاختصار", self._apply_macro_hotkey,
                   RAISED, TEXT, BG).pack(side="right", padx=px(4))
        tk.Label(hotkey_row, text="يبدأ/يوقف الماكرو المحدد", font=font(9), bg=BG, fg=MUTED).pack(side="right", padx=px(8))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=px(18), pady=(0, px(12)))
        left = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        left.pack(side="right", fill="y", padx=(0, px(9)))
        left.configure(width=px(245))
        left.pack_propagate(False)
        tk.Label(left, text="الماكروز", font=font(11, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="e", padx=px(12), pady=(px(10), px(6)))
        self.macro_listbox = tk.Listbox(
            left, bg=SURFACE, fg=TEXT, selectbackground=ACCENT, selectforeground="#FFFFFF",
            highlightthickness=0, bd=0, activestyle="none", font=font(10), exportselection=False,
        )
        self.macro_listbox.pack(fill="both", expand=True, padx=px(7), pady=(0, px(7)))
        self.macro_listbox.bind("<<ListboxSelect>>", self._macro_selected)
        left_actions = tk.Frame(left, bg=SURFACE)
        left_actions.pack(fill="x", padx=px(7), pady=px(6))
        FlatButton(left_actions, "+ جديد", self._new_macro, ACCENT, "#FFFFFF", SURFACE).pack(
            side="right", fill="x", expand=True, padx=(px(3), 0))
        FlatButton(left_actions, "حذف", self._delete_macro, STOP_BG, BAD, SURFACE).pack(
            side="left", fill="x", expand=True, padx=(px(3), 0))
        file_actions = tk.Frame(left, bg=SURFACE)
        file_actions.pack(fill="x", padx=px(7), pady=(0, px(8)))
        FlatButton(file_actions, "استيراد", self._import_macro, RAISED, TEXT, SURFACE).pack(
            side="right", fill="x", expand=True, padx=(px(3), 0))
        FlatButton(file_actions, "تصدير", self._export_macro, RAISED, TEXT, SURFACE).pack(
            side="left", fill="x", expand=True, padx=(px(3), 0))

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        name_row = tk.Frame(right, bg=BG)
        name_row.pack(fill="x", pady=(0, px(7)))
        tk.Label(name_row, text="اسم التسجيل", font=font(9), bg=BG, fg=MUTED).pack(side="right")
        self.macro_name_var = tk.StringVar(value="")
        self.macro_name_entry = tk.Entry(
            name_row, textvariable=self.macro_name_var, justify="right", font=font(11, "bold"),
            bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        self.macro_name_entry.pack(side="right", fill="x", expand=True, padx=(px(8), 0), ipady=px(5))
        self.macro_name_entry.bind("<FocusOut>", self._save_macro_name)
        self.macro_name_entry.bind("<Return>", self._save_macro_name)

        table_frame = tk.Frame(right, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        table_frame.pack(fill="both", expand=True)
        columns = ("delay", "action", "code", "device")
        self.macro_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                       style="Macro.Treeview", selectmode="browse")
        headings = {"device": "النوع", "code": "الزر", "action": "الإجراء", "delay": "الفاصل (مللي ثانية)"}
        widths = {"device": 90, "code": 150, "action": 120, "delay": 140}
        for col in columns:
            self.macro_tree.heading(col, text=headings[col], anchor="center")
            self.macro_tree.column(col, anchor="center", width=px(widths[col]), stretch=(col == "code"))
        tree_scroll = tk.Scrollbar(table_frame, orient="vertical", command=self.macro_tree.yview,
                                   bg=RAISED, troughcolor=BG, activebackground=ACCENT,
                                   bd=0, relief="flat", highlightthickness=0)
        self.macro_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.macro_tree.pack(side="left", fill="both", expand=True)
        self.macro_tree.bind("<Double-1>", self._edit_macro_event)

        event_actions = tk.Frame(right, bg=BG)
        event_actions.pack(fill="x", pady=(px(7), px(5)))
        FlatButton(event_actions, "↑", lambda: self._move_macro_event(-1), RAISED, TEXT, BG).pack(side="right", padx=px(3))
        FlatButton(event_actions, "↓", lambda: self._move_macro_event(1), RAISED, TEXT, BG).pack(side="right", padx=px(3))
        FlatButton(event_actions, "حذف الخطوة", self._delete_macro_event, STOP_BG, BAD, BG).pack(side="right", padx=px(3))
        self.macro_timing_var = tk.StringVar(value="recorded")
        tk.Radiobutton(event_actions, text="التوقيت المسجّل", variable=self.macro_timing_var,
                       value="recorded", command=self._save_macro_timing,
                       bg=BG, fg=TEXT, selectcolor=SURFACE, activebackground=BG,
                       activeforeground=TEXT).pack(side="right", padx=(px(10), px(3)))
        tk.Radiobutton(event_actions, text="فاصل ثابت", variable=self.macro_timing_var,
                       value="fixed", command=self._save_macro_timing,
                       bg=BG, fg=TEXT, selectcolor=SURFACE, activebackground=BG,
                       activeforeground=TEXT).pack(side="right", padx=px(3))
        self.macro_fixed_var = tk.StringVar(value="100")
        self.macro_fixed_entry = tk.Entry(event_actions, textvariable=self.macro_fixed_var,
                                          width=7, justify="center", font=font(9),
                                          bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.macro_fixed_entry.pack(side="right", padx=px(4), ipady=px(3))
        self.macro_fixed_entry.bind("<FocusOut>", self._save_macro_timing)
        self.macro_fixed_entry.bind("<Return>", self._save_macro_timing)

        controls = tk.Frame(right, bg=BG)
        controls.pack(fill="x", pady=(px(4), 0))
        tk.Label(controls, text="التسجيل والتشغيل من نافذة مسجل الإجراءات المستقلة.",
                 font=font(9), bg=BG, fg=MUTED).pack(side="right", padx=px(4))

        self._refresh_macro_list()
        self._render_macro_window()

    def _configure_macro_tree_style(self) -> None:
        try:
            from tkinter import ttk
            style = ttk.Style(self.root)
            style.configure("Macro.Treeview", background=SURFACE, fieldbackground=SURFACE,
                            foreground=TEXT, rowheight=px(30), borderwidth=0)
            style.configure("Macro.Treeview.Heading", background=RAISED, foreground=TEXT,
                            relief="flat", font=font(9, "bold"))
            style.map("Macro.Treeview", background=[("selected", ACCENT)],
                      foreground=[("selected", "#FFFFFF")])
        except (tk.TclError, ImportError):
            pass

    def _build_recorder_window(self) -> None:
        from tkinter import messagebox, simpledialog, ttk

        # The recorder can be opened directly from the F1–F10 window, without
        # opening the macro library first.
        self._macro_messagebox = messagebox
        self._macro_simpledialog = simpledialog

        win = tk.Toplevel(self.root)
        self.recorder_window = win
        win.title("مسجل الإجراءات")
        win.configure(bg=BG)
        win.geometry("1080x720")
        win.minsize(900, 610)
        apply_windows_titlebar(win, self.theme)
        win.protocol("WM_DELETE_WINDOW", self._close_recorder_window)
        self._configure_macro_tree_style()

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=px(22), pady=(px(18), px(12)))
        titles = tk.Frame(top, bg=BG)
        titles.pack(side="right")
        tk.Label(titles, text="مسجل الإجراءات", font=font(20, "bold"), bg=BG, fg=TEXT).pack(anchor="e")
        tk.Label(titles, text="سجّل حركة الماوس وضغطات الكيبورد ثم أعد تشغيلها.",
                 font=font(10), bg=BG, fg=MUTED).pack(anchor="e", pady=(px(3), 0))
        self.recorder_status = tk.Label(top, text="جاهز", font=font(10, "bold"),
                                        bg=RAISED, fg=GOOD, padx=px(12), pady=px(7))
        self.recorder_status.pack(side="left", padx=px(8))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=px(22), pady=(0, px(18)))
        side = tk.Frame(body, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        side.pack(side="right", fill="y", padx=(0, px(12)))
        side.configure(width=px(250))
        side.pack_propagate(False)
        tk.Label(side, text="اختَر تسجيلًا", font=font(11, "bold"), bg=SURFACE, fg=TEXT).pack(
            anchor="e", padx=px(12), pady=(px(12), px(7)))
        self.recorder_listbox = tk.Listbox(
            side, bg=SURFACE, fg=TEXT, selectbackground=ACCENT, selectforeground="#FFFFFF",
            highlightthickness=0, bd=0, activestyle="none", font=font(10), exportselection=False,
        )
        self.recorder_listbox.pack(fill="both", expand=True, padx=px(8), pady=(0, px(8)))
        self.recorder_listbox.bind("<<ListboxSelect>>", self._recorder_macro_selected)
        FlatButton(side, "+ تسجيل جديد", self._new_recorder_macro, ACCENT, "#FFFFFF", SURFACE).pack(
            fill="x", padx=px(8), pady=(0, px(6)))
        FlatButton(side, "فتح مكتبة الماكروز", self._on_macros, RAISED, TEXT, SURFACE).pack(
            fill="x", padx=px(8), pady=(0, px(10)))

        content = tk.Frame(body, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        name_row = tk.Frame(content, bg=BG)
        name_row.pack(fill="x", pady=(0, px(8)))
        tk.Label(name_row, text="اسم التسجيل", font=font(9, "bold"), bg=BG, fg=MUTED).pack(side="right")
        self.recorder_name_var = tk.StringVar(value="")
        self.recorder_name_entry = tk.Entry(
            name_row, textvariable=self.recorder_name_var, justify="right", font=font(11, "bold"),
            bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT,
        )
        self.recorder_name_entry.pack(side="right", fill="x", expand=True, padx=(px(9), 0), ipady=px(5))
        self.recorder_name_entry.bind("<FocusOut>", self._save_recorder_name)
        self.recorder_name_entry.bind("<Return>", self._save_recorder_name)

        repeat_row = tk.Frame(content, bg=BG)
        repeat_row.pack(fill="x", pady=(0, px(9)))
        tk.Label(repeat_row, text="إجمالي مرات التشغيل", font=font(9), bg=BG, fg=MUTED).pack(side="right")
        self.recorder_repeat_var = tk.StringVar(value="1")
        self.recorder_repeat_entry = tk.Entry(
            repeat_row, textvariable=self.recorder_repeat_var, width=9, justify="center",
            font=font(10), bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
        )
        self.recorder_repeat_entry.pack(side="right", padx=px(8), ipady=px(4))
        self.recorder_repeat_entry.bind("<FocusOut>", self._save_recorder_repeat)
        self.recorder_repeat_entry.bind("<Return>", self._save_recorder_repeat)
        self.recorder_repeat_forever_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            repeat_row, text="مستمر حتى الإيقاف", variable=self.recorder_repeat_forever_var,
            command=self._save_recorder_repeat, bg=BG, fg=TEXT, selectcolor=SURFACE,
            activebackground=BG, activeforeground=TEXT,
        ).pack(side="right", padx=px(8))

        table_frame = tk.Frame(content, bg=SURFACE, highlightthickness=1, highlightbackground=LINE)
        table_frame.pack(fill="both", expand=True)
        columns = ("delay", "action", "code", "device")
        self.recorder_tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                          style="Macro.Treeview", selectmode="browse")
        headings = {"device": "النوع", "code": "الزر / الموضع", "action": "الإجراء",
                    "delay": "الفاصل (مللي ثانية)"}
        widths = {"device": 100, "code": 180, "action": 120, "delay": 150}
        for col in columns:
            self.recorder_tree.heading(col, text=headings[col], anchor="center")
            self.recorder_tree.column(col, anchor="center", width=px(widths[col]), stretch=(col == "code"))
        tree_scroll = tk.Scrollbar(table_frame, orient="vertical", command=self.recorder_tree.yview,
                                   width=px(12), bg=RAISED, troughcolor=BG,
                                   activebackground=ACCENT, bd=0, relief="flat", highlightthickness=0)
        tree_scroll.pack(side="right", fill="y")
        self.recorder_tree.configure(yscrollcommand=tree_scroll.set)
        self.recorder_tree.pack(side="left", fill="both", expand=True)
        self.recorder_tree.bind("<Double-1>", lambda event: self._edit_macro_event(
            event, tree=self.recorder_tree, parent=self.recorder_window))

        edit_row = tk.Frame(content, bg=BG)
        edit_row.pack(fill="x", pady=(px(7), px(4)))
        FlatButton(edit_row, "↑", lambda: self._move_macro_event(-1, self.recorder_tree), RAISED, TEXT, BG).pack(side="right", padx=px(3))
        FlatButton(edit_row, "↓", lambda: self._move_macro_event(1, self.recorder_tree), RAISED, TEXT, BG).pack(side="right", padx=px(3))
        FlatButton(edit_row, "حذف الخطوة", lambda: self._delete_macro_event(self.recorder_tree), STOP_BG, BAD, BG).pack(side="right", padx=px(3))
        self.recorder_timing_var = tk.StringVar(value="recorded")
        tk.Radiobutton(edit_row, text="التوقيت المسجّل", variable=self.recorder_timing_var,
                       value="recorded", command=self._save_recorder_timing,
                       bg=BG, fg=TEXT, selectcolor=SURFACE, activebackground=BG,
                       activeforeground=TEXT).pack(side="left", padx=(px(8), px(3)))
        tk.Radiobutton(edit_row, text="فاصل ثابت", variable=self.recorder_timing_var,
                       value="fixed", command=self._save_recorder_timing,
                       bg=BG, fg=TEXT, selectcolor=SURFACE, activebackground=BG,
                       activeforeground=TEXT).pack(side="left", padx=px(3))
        self.recorder_fixed_var = tk.StringVar(value="100")
        self.recorder_fixed_entry = tk.Entry(edit_row, textvariable=self.recorder_fixed_var,
                                             width=7, justify="center", font=font(9),
                                             bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.recorder_fixed_entry.pack(side="left", padx=px(4), ipady=px(3))
        self.recorder_fixed_entry.bind("<FocusOut>", self._save_recorder_timing)
        self.recorder_fixed_entry.bind("<Return>", self._save_recorder_timing)

        controls = tk.Frame(content, bg=BG)
        controls.pack(fill="x", pady=(px(4), 0))
        self.recorder_start_btn = FlatButton(controls, "بدء التسجيل", lambda: None, ACCENT, "#FFFFFF", BG)
        self.recorder_start_btn.command = self._start_macro_recording
        self.recorder_start_btn.pack(side="right", fill="x", expand=True, padx=(px(4), 0))
        self.recorder_stop_record_btn = FlatButton(controls, "إنهاء التسجيل", lambda: None, RAISED, TEXT, BG)
        self.recorder_stop_record_btn.command = self._stop_macro_recording
        self.recorder_stop_record_btn.pack(side="right", fill="x", expand=True, padx=px(4))
        self.recorder_play_btn = FlatButton(controls, "تشغيل", lambda: None, GOOD, "#FFFFFF", BG)
        self.recorder_play_btn.command = self._play_macro_once
        self.recorder_play_btn.pack(side="right", fill="x", expand=True, padx=px(4))
        self.recorder_stop_btn = FlatButton(controls, "إيقاف", self.c.stop_macro, STOP_BG, BAD, BG)
        self.recorder_stop_btn.pack(side="right", fill="x", expand=True, padx=(0, px(4)))

        self._refresh_recorder_list()
        self._render_recorder_window()

    def _close_recorder_window(self) -> None:
        if self.c.state.macro_recording:
            self.c.stop_recording()
        if self.c.state.macro_playing:
            self.c.stop_macro()
        if self.recorder_window is not None:
            self.recorder_window.destroy()
            self.recorder_window = None
        self._refresh_macro_list(self.c._selected_macro_id)

    def _close_macro_window(self) -> None:
        if getattr(self, "macro_window", None) is not None:
            self.macro_window.destroy()
            self.macro_window = None

    def _selected_macro(self):
        return self.c.get_macro()

    def _refresh_macro_list(self, select_id=None) -> None:
        if not getattr(self, "macro_listbox", None):
            return
        self.macro_listbox.delete(0, "end")
        macros = self.c.macro_store.macros
        selected = select_id or self.c._selected_macro_id
        for index, macro in enumerate(macros):
            self.macro_listbox.insert("end", "%s   ·   %d" % (macro.name, len(macro.events)))
            if macro.id == selected:
                self.macro_listbox.selection_set(index)
                self.macro_listbox.activate(index)
        if selected:
            self.c.select_macro(selected)
        self._refresh_macro_detail()
        self._refresh_recorder_list(selected)
        self._macro_ui_signature = self._macro_signature()

    def _macro_signature(self):
        return (
            self.c._selected_macro_id,
            tuple((macro.id, macro.name, macro.timing_mode, macro.fixed_delay_ms,
                   macro.repeat_count, macro.repeat_forever,
                   tuple((event.device, event.code, event.action, event.delay_ms,
                          event.scan_code, event.virtual_key, event.extended, event.x, event.y)
                         for event in macro.events))
                  for macro in self.c.macro_store.macros),
        )

    def _refresh_macro_detail(self) -> None:
        macro = self._selected_macro()
        if macro is None:
            self.macro_name_var.set("")
            self.macro_timing_var.set("recorded")
            self.macro_fixed_var.set("100")
            for item in self.macro_tree.get_children():
                self.macro_tree.delete(item)
            return
        if self.macro_window.focus_get() is not self.macro_name_entry:
            self.macro_name_var.set(macro.name)
        self.macro_timing_var.set(macro.timing_mode)
        self.macro_fixed_var.set(str(macro.fixed_delay_ms))
        for item in self.macro_tree.get_children():
            self.macro_tree.delete(item)
        for index, event in enumerate(macro.events):
            self.macro_tree.insert("", "end", iid=str(index), values=(
                event.delay_ms, "حركة" if event.action == "move" else ("ضغط" if event.action == "down" else "إفلات"),
                self._macro_event_name(event), "كيبورد" if event.device == "key" else "ماوس",
            ))

    def _refresh_recorder_list(self, select_id=None) -> None:
        if self.recorder_window is None or not hasattr(self, "recorder_listbox"):
            return
        self.recorder_listbox.delete(0, "end")
        selected = select_id or self.c._selected_macro_id
        for index, macro in enumerate(self.c.macro_store.macros):
            self.recorder_listbox.insert("end", "%s   ·   %d" % (macro.name, len(macro.events)))
            if macro.id == selected:
                self.recorder_listbox.selection_set(index)
                self.recorder_listbox.activate(index)
        if selected:
            self.c.select_macro(selected)
        self._refresh_recorder_detail()
        self._recorder_ui_signature = self._macro_signature()

    def _refresh_recorder_detail(self) -> None:
        if self.recorder_window is None:
            return
        macro = self._selected_macro()
        if macro is None:
            if self.recorder_window.focus_get() is not self.recorder_name_entry:
                self.recorder_name_var.set("")
            self.recorder_repeat_var.set("1")
            self.recorder_repeat_forever_var.set(False)
            self.recorder_timing_var.set("recorded")
            self.recorder_fixed_var.set("100")
            for item in self.recorder_tree.get_children():
                self.recorder_tree.delete(item)
            return
        if self.recorder_window.focus_get() is not self.recorder_name_entry:
            self.recorder_name_var.set(macro.name)
        if self.recorder_window.focus_get() is not self.recorder_repeat_entry:
            self.recorder_repeat_var.set(str(macro.repeat_count))
        self.recorder_repeat_forever_var.set(macro.repeat_forever)
        self.recorder_timing_var.set(macro.timing_mode)
        self.recorder_fixed_var.set(str(macro.fixed_delay_ms))
        for item in self.recorder_tree.get_children():
            self.recorder_tree.delete(item)
        for index, event in enumerate(macro.events):
            self.recorder_tree.insert("", "end", iid=str(index), values=(
                event.delay_ms, "حركة" if event.action == "move" else ("ضغط" if event.action == "down" else "إفلات"),
                self._macro_event_name(event), "كيبورد" if event.device == "key" else "ماوس",
            ))

    def _macro_event_name(self, event) -> str:
        if event.device == "mouse":
            if event.code == "move":
                return "(%d، %d)" % (event.x, event.y)
            return {"left": "زر أيسر", "right": "زر أيمن", "middle": "عجلة", "x1": "جانبي 1", "x2": "جانبي 2"}.get(event.code, event.code)
        vk = event.virtual_key
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk)
        if 0x70 <= vk <= 0x87:
            return "F%d" % (vk - 0x6F)
        names = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
                 0x11: "Ctrl", 0x12: "Alt", 0x1B: "Esc", 0x20: "Space",
                 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2E: "Delete"}
        return names.get(vk, "Scan %02X" % event.scan_code)

    def _macro_selected(self, _event=None) -> None:
        selection = self.macro_listbox.curselection()
        if selection:
            macro = self.c.macro_store.macros[int(selection[0])]
            self.c.select_macro(macro.id)
            self._refresh_macro_detail()
            self._refresh_recorder_list(macro.id)

    def _recorder_macro_selected(self, _event=None) -> None:
        selection = self.recorder_listbox.curselection()
        if selection:
            macro = self.c.macro_store.macros[int(selection[0])]
            self.c.select_macro(macro.id)
            self._refresh_recorder_detail()
            self._refresh_macro_list(macro.id)

    def _new_macro(self) -> None:
        try:
            macro = self.c.create_macro()
            self._refresh_macro_list(macro.id)
        except ValueError as exc:
            self._macro_messagebox.showerror("تعذّر إنشاء ماكرو", str(exc), parent=self.macro_window)

    def _delete_macro(self) -> None:
        macro = self._selected_macro()
        if not macro:
            return
        if self._macro_messagebox.askyesno("حذف ماكرو", "هل تريد حذف «%s»؟" % macro.name,
                                           parent=self.macro_window):
            self.c.delete_macro(macro.id)
            self._refresh_macro_list()

    def _save_macro_name(self, _event=None) -> None:
        macro = self._selected_macro()
        if macro and self.macro_name_var.get().strip() != macro.name:
            self.c.update_macro(macro.id, name=self.macro_name_var.get())
            self._refresh_macro_list(macro.id)

    def _save_macro_timing(self, _event=None) -> None:
        macro = self._selected_macro()
        if not macro:
            return
        try:
            fixed = max(0, min(DELAY_MAX, int(self.macro_fixed_var.get() or "0")))
        except ValueError:
            fixed = macro.fixed_delay_ms
        self.c.update_macro(macro.id, timing_mode=self.macro_timing_var.get(), fixed_delay_ms=fixed)

    def _save_recorder_name(self, _event=None) -> None:
        macro = self._selected_macro()
        if macro and self.recorder_name_var.get().strip() != macro.name:
            self.c.update_macro(macro.id, name=self.recorder_name_var.get())
            self._refresh_macro_list(macro.id)

    def _save_recorder_timing(self, _event=None) -> None:
        macro = self._selected_macro()
        if not macro:
            return
        try:
            fixed = max(0, min(DELAY_MAX, int(self.recorder_fixed_var.get() or "0")))
        except ValueError:
            fixed = macro.fixed_delay_ms
        self.c.update_macro(
            macro.id, timing_mode=self.recorder_timing_var.get(), fixed_delay_ms=fixed,
        )

    def _save_recorder_repeat(self, _event=None) -> None:
        macro = self._selected_macro()
        if not macro:
            return
        from .macros import MAX_REPEAT_COUNT
        try:
            count = max(1, min(MAX_REPEAT_COUNT, int(self.recorder_repeat_var.get() or "1")))
        except ValueError:
            count = macro.repeat_count
        self.recorder_repeat_var.set(str(count))
        self.c.update_macro(
            macro.id, repeat_count=count,
            repeat_forever=self.recorder_repeat_forever_var.get(),
        )

    def _new_recorder_macro(self) -> None:
        try:
            macro = self.c.create_macro()
            self._refresh_macro_list(macro.id)
            self._refresh_recorder_list(macro.id)
        except ValueError as exc:
            self._macro_messagebox.showerror("تعذّر إنشاء تسجيل", str(exc), parent=self.recorder_window)

    def _start_macro_recording(self) -> None:
        macro = self._selected_macro()
        parent = self.recorder_window or self.macro_window
        if macro and macro.events and not self._macro_messagebox.askyesno(
                "استبدال التسجيل", "سيتم استبدال خطوات «%s» بالتسجيل الجديد. متابعة؟" % macro.name,
                parent=parent):
            return
        if not macro:
            try:
                macro = self.c.create_macro()
            except ValueError as exc:
                self._macro_messagebox.showerror("تعذّر إنشاء ماكرو", str(exc), parent=parent)
                return
        if self.c.start_recording(macro.id):
            self._refresh_macro_list(macro.id)
            self._refresh_recorder_list(macro.id)
            self._render_macro_window()
            self._render_recorder_window()

    def _stop_macro_recording(self) -> None:
        if self.c.stop_recording():
            self._refresh_macro_list(self.c._selected_macro_id)
            self._refresh_recorder_list(self.c._selected_macro_id)
            self._render_macro_window()
            self._render_recorder_window()

    def _play_macro_once(self) -> None:
        macro = self._selected_macro()
        if macro:
            self._save_recorder_repeat()
            self.c.play_macro(macro.id)

    def _play_macro_loop(self) -> None:
        macro = self._selected_macro()
        if macro:
            self.c.update_macro(macro.id, repeat_forever=True)
            self.recorder_repeat_forever_var.set(True)
            self.c.play_macro(macro.id)

    def _move_macro_event(self, direction: int, tree=None) -> None:
        macro = self._selected_macro()
        tree = tree or self.macro_tree
        selection = tree.selection()
        if not macro or not selection:
            return
        index = int(selection[0])
        target = max(0, min(len(macro.events) - 1, index + direction))
        if target == index:
            return
        events = list(macro.events)
        events[index], events[target] = events[target], events[index]
        self.c.update_macro(macro.id, events=events)
        self._refresh_macro_list(macro.id)
        tree.selection_set(str(target))

    def _delete_macro_event(self, tree=None) -> None:
        macro = self._selected_macro()
        tree = tree or self.macro_tree
        selection = tree.selection()
        if not macro or not selection:
            return
        index = int(selection[0])
        events = list(macro.events)
        events.pop(index)
        if events and index == 0:
            events[0].delay_ms = 0
        elif events:
            events[index].delay_ms = min(
                DELAY_MAX, events[index].delay_ms + macro.events[index].delay_ms
            )
        self.c.update_macro(macro.id, events=events)
        self._refresh_macro_list(macro.id)

    def _edit_macro_event(self, event, tree=None, parent=None) -> None:
        tree = tree or self.macro_tree
        parent = parent or self.macro_window
        row = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        if not row or column != "#1":
            return
        macro = self._selected_macro()
        if not macro:
            return
        index = int(row)
        value = self._macro_simpledialog.askinteger(
            "تعديل الفاصل", "الفاصل قبل هذه الخطوة بالمللي ثانية:",
            initialvalue=macro.events[index].delay_ms, minvalue=0, maxvalue=DELAY_MAX,
            parent=parent,
        )
        if value is not None:
            events = list(macro.events)
            events[index].delay_ms = value
            self.c.update_macro(macro.id, events=events)
            self._refresh_macro_list(macro.id)

    def _import_macro(self) -> None:
        path = self._macro_filedialog.askopenfilename(
            parent=self.macro_window, title="استيراد ماكرو", filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            macro = self.c.import_macro(path)
            self._refresh_macro_list(macro.id)
        except (OSError, ValueError) as exc:
            self._macro_messagebox.showerror("تعذّر الاستيراد", str(exc), parent=self.macro_window)

    def _export_macro(self) -> None:
        macro = self._selected_macro()
        if not macro:
            return
        path = self._macro_filedialog.asksaveasfilename(
            parent=self.macro_window, title="تصدير ماكرو", defaultextension=".json",
            initialfile=macro.name + ".json", filetypes=[("Macro JSON", "*.json")])
        if path:
            try:
                self.c.macro_store.export_macro(macro, path)
            except OSError as exc:
                self._macro_messagebox.showerror("تعذّر التصدير", str(exc), parent=self.macro_window)

    def _apply_macro_hotkey(self) -> None:
        try:
            chord = self.c.set_macro_hotkey(self.macro_hotkey_var.get())
            self.macro_hotkey_var.set(chord)
        except ValueError:
            self._macro_messagebox.showerror(
                "اختصار غير صالح", "استخدم مثلًا Ctrl+Shift+F11 أو Ctrl+Alt+M.",
                parent=self.macro_window,
            )

    def _render_macro_window(self) -> None:
        win = getattr(self, "macro_window", None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            if self.c.state.macro_hotkey_ok is False:
                self.macro_status.configure(text="الاختصار غير متاح", fg=WARN)
            else:
                self.macro_status.configure(
                    text="%d تسجيلات" % len(self.c.macro_store.macros), fg=MUTED,
                )
            if getattr(self, "_macro_ui_signature", None) != self._macro_signature():
                self._refresh_macro_list(self.c._selected_macro_id)
        except tk.TclError:
            pass

    def _render_recorder_window(self) -> None:
        win = self.recorder_window
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            state = self.c.state
            if state.macro_recording:
                self.recorder_status.configure(text="● جاري التسجيل", bg=STOP_BG, fg=BAD)
            elif state.macro_playing:
                self.recorder_status.configure(text="▶ جاري التشغيل", bg=PRESS, fg=GOOD)
            elif state.macro_hotkey_ok is False:
                self.recorder_status.configure(text="الاختصار غير متاح", bg=STOP_BG, fg=WARN)
            else:
                self.recorder_status.configure(text="جاهز للتسجيل", bg=RAISED, fg=GOOD)
            busy = state.macro_recording or state.macro_playing or state.running
            self.recorder_start_btn.set_enabled(not busy)
            self.recorder_stop_record_btn.set_enabled(state.macro_recording)
            macro = self._selected_macro()
            self.recorder_play_btn.set_enabled(bool(macro and macro.events) and not busy)
            self.recorder_stop_btn.set_enabled(state.macro_recording or state.macro_playing)
            if getattr(self, "_recorder_ui_signature", None) != self._macro_signature():
                self._refresh_recorder_list(self.c._selected_macro_id)
        except tk.TclError:
            pass

    def _on_admin(self) -> None:
        if self.c.relaunch_as_admin():
            self._on_close()
        else:
            self.render()

    def _on_close(self) -> None:
        try:
            if self.root.state() != "withdrawn":
                self.c.settings.window_x = self.root.winfo_x()
                self.c.settings.window_y = self.root.winfo_y()
        except tk.TclError:
            pass
        self.c.close()
        self.root.destroy()

    def _poll(self) -> None:
        try:
            if self.c.tick():
                self.render()
        except Exception:
            log.exception("UI update failed")
        self.root.after(self.POLL_MS, self._poll)

    def run(self) -> None:
        self.c.start_services()
        self.root.after(self.POLL_MS, self._poll)
        self.root.mainloop()
