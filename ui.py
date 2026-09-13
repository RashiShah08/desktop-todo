"""Main window UI — borderless cute desktop widget built on CustomTkinter.

Design philosophy:
  • Calm, premium feel — Linear/Things 3 inspired
  • Generous whitespace
  • Pill-style tags for metadata
  • Hand-drawn flower mascot
  • Soft purple accent on warm-lavender background

All Windows-only Win32 calls go through windows_integration.py — they're
all best-effort and fail open."""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Callable

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from data import TodoStore, Task
import styles as S
import windows_integration as winapi
import news as news_mod
import gcal
import mascot


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def fmt_indian_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def parse_indian_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def time_12h_to_24h(hour: str, minute: str, ampm: str) -> Optional[str]:
    try:
        h = int(hour); m = int(minute)
    except (ValueError, TypeError):
        return None
    if not (1 <= h <= 12 and 0 <= m <= 59):
        return None
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def time_24h_to_12h(hhmm: Optional[str]) -> tuple[str, str, str]:
    if not hhmm:
        return ("9", "00", "AM")
    try:
        h, m = hhmm.split(":")
        h = int(h); m = int(m)
    except (ValueError, TypeError):
        return ("9", "00", "AM")
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return (str(h12), f"{m:02d}", ampm)


def greeting_for(now: datetime, name: str) -> tuple[str, str]:
    """Returns (greeting, tagline) — deterministic per-day so it doesn't flicker."""
    h = now.hour
    if h < 12:
        gpool, tpool = S.GREETINGS_MORNING, S.GREETING_TAGLINES_MORNING
    elif h < 17:
        gpool, tpool = S.GREETINGS_AFTERNOON, S.GREETING_TAGLINES_AFTERNOON
    else:
        gpool, tpool = S.GREETINGS_EVENING, S.GREETING_TAGLINES_EVENING
    day = now.toordinal()
    return (gpool[day % len(gpool)].format(name=name),
            tpool[day % len(tpool)])


def fmt_date_pretty(d: date) -> str:
    return d.strftime("%A, %d %B")


# Mascot caching — load PIL image once, wrap in CTkImage on demand
_mascot_pil_cache: dict[int, "Image"] = {}


def _ctk_mascot(size: int):
    """Return a CTkImage of the mascot at the given pixel size. None on failure."""
    if not mascot.HAS_PIL:
        return None
    img = _mascot_pil_cache.get(size)
    if img is None:
        img = mascot.get_mascot(size=size)
        if img is None:
            return None
        _mascot_pil_cache[size] = img
    try:
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Animation helper — smooth height/value tweens via Tk's after()
# ─────────────────────────────────────────────────────────────────────

def animate(widget, prop: str, start, end, steps: int = 10,
            duration_ms: int = 160, on_complete=None):
    """Tween a numeric widget property from start → end.
    Safe to call mid-animation; the new tween overrides the old one
    when the widget reaches its next step."""
    if steps < 1:
        steps = 1
    interval = max(8, duration_ms // steps)
    delta = (end - start) / steps

    def step(i):
        if not widget.winfo_exists():
            return
        try:
            val = start + delta * (i + 1)
            widget.configure(**{prop: int(val)})
        except Exception:
            return
        if i + 1 >= steps:
            try:
                widget.configure(**{prop: int(end)})
            except Exception:
                pass
            if on_complete:
                try:
                    widget.after(0, on_complete)
                except Exception:
                    pass
            return
        widget.after(interval, lambda: step(i + 1))
    step(-1)


# ─────────────────────────────────────────────────────────────────────
# Date Picker — CTk button that opens a tkcalendar popup
# ─────────────────────────────────────────────────────────────────────

class DatePickerButton(ctk.CTkButton):
    """A CTk button that, when clicked, pops up a beautiful calendar widget.
    Stores the selected date as a Python date object."""

    def __init__(self, parent, initial=None, on_change=None,
                 placeholder: str = "Pick date…", **kwargs):
        self._date: Optional[date] = initial
        self._on_change = on_change
        self._placeholder = placeholder
        # Defaults — caller can override via kwargs
        defaults = dict(
            text=self._display_text(),
            anchor="w",
            font=S.FONT_BODY,
            height=34,
            fg_color=S.BG_CARD_ALT,
            text_color=S.TEXT_PRIMARY,
            hover_color=S.BG_PILL,
            border_width=1,
            border_color=S.BORDER_LIGHT,
            corner_radius=S.RADIUS_BUTTON,
        )
        defaults.update(kwargs)
        super().__init__(parent, **defaults)
        self.configure(command=self._open_popup)

    def _display_text(self) -> str:
        if self._date:
            return "📅  " + self._date.strftime("%d/%m/%Y")
        return "📅  " + self._placeholder

    def _open_popup(self):
        try:
            from tkcalendar import Calendar
        except ImportError:
            messagebox.showinfo(
                "Calendar widget missing",
                "Install tkcalendar to use the calendar picker:\n\n"
                "  python -m pip install tkcalendar",
                parent=self.winfo_toplevel())
            return
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=S.BG_CARD)
        popup.attributes("-topmost", True)

        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        popup.geometry(f"+{x}+{y}")
        popup.lift()
        try:
            popup.focus_force()
        except Exception:
            pass

        wrap = tk.Frame(popup, bg=S.BG_CARD, bd=1, relief="solid",
                        highlightthickness=0)
        wrap.pack(padx=0, pady=0)
        wrap.configure(highlightbackground=S.BORDER_LIGHT)

        cal = Calendar(
            wrap, selectmode="day",
            date_pattern="dd/mm/yyyy",
            background=S.ACCENT, foreground="white",
            headersbackground=S.ACCENT_TINT, headersforeground=S.TEXT_PRIMARY,
            normalbackground=S.BG_CARD, normalforeground=S.TEXT_PRIMARY,
            weekendbackground=S.BG_CARD_ALT, weekendforeground=S.TEXT_PRIMARY,
            selectbackground=S.ACCENT, selectforeground="white",
            bordercolor=S.BORDER_LIGHT,
            othermonthbackground=S.BG_CARD_ALT,
            othermonthforeground=S.TEXT_MUTED,
            othermonthwebackground=S.BG_CARD_ALT,
            othermonthweforeground=S.TEXT_MUTED,
            font=(S.FONT_FAMILY, 10),
            headersborderwidth=0,
            borderwidth=0,
            showweeknumbers=False,
        )
        if self._date:
            cal.selection_set(self._date)
        cal.pack(padx=8, pady=8)

        btn_row = tk.Frame(wrap, bg=S.BG_CARD)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))

        def _accept():
            try:
                self._date = cal.selection_get()
            except Exception:
                self._date = None
            self.configure(text=self._display_text())
            if self._on_change:
                try:
                    self._on_change(self._date)
                except Exception:
                    pass
            popup.destroy()

        def _clear():
            self._date = None
            self.configure(text=self._display_text())
            if self._on_change:
                try:
                    self._on_change(None)
                except Exception:
                    pass
            popup.destroy()

        ctk.CTkButton(btn_row, text="Done", height=28,
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_BODY_BOLD,
                      command=_accept
                      ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(btn_row, text="Clear", height=28, width=64,
                      fg_color=S.BG_CARD_ALT, text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_PILL_HOVER,
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_SMALL,
                      command=_clear).pack(side="right")
        ctk.CTkButton(btn_row, text="Cancel", height=28, width=64,
                      fg_color="transparent", text_color=S.TEXT_MUTED,
                      hover_color=S.BG_CARD_ALT,
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_SMALL,
                      command=popup.destroy
                      ).pack(side="right", padx=(0, 4))

        popup.bind("<Escape>", lambda _e: popup.destroy())

    def get_date(self):
        return self._date

    def set_date(self, d):
        self._date = d
        self.configure(text=self._display_text())

    def clear(self):
        self.set_date(None)


# ─────────────────────────────────────────────────────────────────────
# Custom modern calendar — replaces tkcalendar's old-school widget
# ─────────────────────────────────────────────────────────────────────

class CalendarPopup(ctk.CTkToplevel):
    """Pretty CTk-only calendar. Click a day, hit OK."""

    def __init__(self, parent, initial=None, on_pick=None):
        super().__init__(parent)
        self.on_pick = on_pick
        self._selected = initial
        base = initial or date.today()
        self._view_year = base.year
        self._view_month = base.month

        self.overrideredirect(True)
        self.configure(fg_color=S.BG_CARD)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self._build()
        try:
            self.focus_force()
        except Exception:
            pass
        self.bind("<Escape>", lambda _e: self.destroy())

        # Position centered horizontally over the parent widget,
        # just below it. Clamp to screen if needed.
        try:
            self.update_idletasks()
            pop_w = self.winfo_width()
            pop_h = self.winfo_height()
            anchor_x = parent.winfo_rootx() + parent.winfo_width() // 2 - pop_w // 2
            anchor_y = parent.winfo_rooty() + parent.winfo_height() + 6
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            anchor_x = max(8, min(anchor_x, sw - pop_w - 8))
            anchor_y = max(8, min(anchor_y, sh - pop_h - 40))
            self.geometry(f"+{anchor_x}+{anchor_y}")
        except Exception:
            pass

    def _build(self):
        wrap = ctk.CTkFrame(self, fg_color=S.BG_CARD,
                            corner_radius=S.RADIUS_CARD,
                            border_width=1, border_color=S.BORDER_LIGHT)
        wrap.pack(padx=2, pady=2)
        self._wrap = wrap

        # Month navigator
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkButton(head, text="‹", width=22, height=22,
                      fg_color="transparent", text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_PILL,
                      font=(S.FONT_FAMILY, 14, "bold"),
                      corner_radius=S.RADIUS_BUTTON,
                      command=self._prev_month).pack(side="left")
        self.title_lbl = ctk.CTkLabel(head, text=self._title_text(),
                                       font=S.FONT_BODY_BOLD,
                                       text_color=S.TEXT_PRIMARY,
                                       anchor="center")
        self.title_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(head, text="›", width=22, height=22,
                      fg_color="transparent", text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_PILL,
                      font=(S.FONT_FAMILY, 14, "bold"),
                      corner_radius=S.RADIUS_BUTTON,
                      command=self._next_month).pack(side="left")

        # Day-of-week header — bigger letters
        dow_row = ctk.CTkFrame(wrap, fg_color="transparent")
        dow_row.pack(fill="x", padx=10)
        for d in ("M", "T", "W", "T", "F", "S", "S"):
            ctk.CTkLabel(dow_row, text=d, width=32, height=22,
                         font=S.FONT_CAPTION, text_color=S.TEXT_MUTED
                         ).pack(side="left", padx=1)

        # Day grid — bigger cells for a more luxurious feel
        self.day_grid = ctk.CTkFrame(wrap, fg_color="transparent")
        self.day_grid.pack(padx=10, pady=(2, 8))
        self._build_grid()

        # Bottom buttons
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btns, text="cancel", height=26,
                      fg_color="transparent", text_color=S.TEXT_MUTED,
                      hover_color=S.BG_CARD_ALT,
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_TINY,
                      command=self.destroy).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ctk.CTkButton(btns, text="today", height=26,
                      fg_color=S.BG_PILL, text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_PILL_HOVER,
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_TINY,
                      command=self._jump_today).pack(side="left", fill="x", expand=True, padx=3)
        ctk.CTkButton(btns, text="ok", height=26,
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      corner_radius=S.RADIUS_BUTTON,
                      font=S.FONT_BODY_BOLD,
                      command=self._accept).pack(side="left", fill="x", expand=True, padx=(3, 0))

    def _title_text(self):
        import calendar as _cm
        return f"{_cm.month_name[self._view_month]} {self._view_year}"

    def _build_grid(self):
        import calendar as _cm
        for w in list(self.day_grid.winfo_children()):
            try: w.destroy()
            except Exception: pass
        cal = _cm.Calendar(firstweekday=0)   # Monday first
        weeks = cal.monthdayscalendar(self._view_year, self._view_month)
        today = date.today()
        for week in weeks:
            row = ctk.CTkFrame(self.day_grid, fg_color="transparent")
            row.pack(fill="x")
            for d in week:
                if d == 0:
                    ctk.CTkFrame(row, width=32, height=28,
                                 fg_color="transparent"
                                 ).pack(side="left", padx=1, pady=1)
                    continue
                this_date = date(self._view_year, self._view_month, d)
                is_today = (this_date == today)
                is_selected = (this_date == self._selected)
                if is_selected:
                    fg = S.ACCENT
                    text_color = "white"
                    border_w = 0
                    border_color = S.ACCENT
                elif is_today:
                    fg = "transparent"
                    text_color = S.ACCENT
                    border_w = 1
                    border_color = S.ACCENT
                else:
                    fg = "transparent"
                    text_color = S.TEXT_PRIMARY
                    border_w = 0
                    border_color = S.BORDER_LIGHT
                font = S.FONT_BODY_BOLD if (is_today or is_selected) else S.FONT_SMALL
                btn = ctk.CTkButton(
                    row, text=str(d), width=32, height=28,
                    fg_color=fg, text_color=text_color,
                    hover_color=S.ACCENT_TINT,
                    font=font,
                    corner_radius=999,
                    border_width=border_w,
                    border_color=border_color,
                    command=lambda dt=this_date: self._select(dt))
                btn.pack(side="left", padx=1, pady=1)

    def _select(self, dt):
        self._selected = dt
        self._build_grid()

    def _prev_month(self):
        self._view_month -= 1
        if self._view_month < 1:
            self._view_month = 12
            self._view_year -= 1
        self.title_lbl.configure(text=self._title_text())
        self._build_grid()

    def _next_month(self):
        self._view_month += 1
        if self._view_month > 12:
            self._view_month = 1
            self._view_year += 1
        self.title_lbl.configure(text=self._title_text())
        self._build_grid()

    def _jump_today(self):
        t = date.today()
        self._view_year = t.year
        self._view_month = t.month
        self._selected = t
        self.title_lbl.configure(text=self._title_text())
        self._build_grid()

    def _accept(self):
        if self.on_pick:
            try:
                self.on_pick(self._selected)
            except Exception:
                pass
        self.destroy()


# ─────────────────────────────────────────────────────────────────────
# Quick Date Picker — chip row for common dates + calendar popup
# ─────────────────────────────────────────────────────────────────────

class QuickDatePicker(ctk.CTkFrame):
    """One-row date input: [today] [tom.] [week] [pick] [×]
    Tap a chip to pick a relative date. Tap [pick] for full calendar.
    Tap [×] (only visible when a date is set) to clear."""

    def __init__(self, parent, initial=None, on_change=None):
        super().__init__(parent, fg_color="transparent")
        self._date = initial
        self._on_change = on_change
        self._build()

    def _build(self):
        self.btn_today = self._chip("today")
        self.btn_tom = self._chip("tom.")
        self.btn_week = self._chip("week")
        self.btn_pick = self._chip("pick")
        self.btn_clear = self._chip("✕", small=True)

        # Wire commands
        today = date.today()
        self.btn_today.configure(command=lambda: self._set(today))
        self.btn_tom.configure(command=lambda: self._set(today + timedelta(days=1)))
        self.btn_week.configure(command=lambda: self._set(today + timedelta(days=7)))
        self.btn_pick.configure(command=self._open_popup)
        self.btn_clear.configure(command=lambda: self._set(None))

        for b in (self.btn_today, self.btn_tom, self.btn_week, self.btn_pick):
            b.pack(side="left", fill="x", expand=True, padx=1)
        # clear button packed only when there's a date set
        self._refresh_chips()

    def _chip(self, text, small=False):
        return ctk.CTkButton(
            self, text=text, height=22,
            width=20 if small else 0,
            fg_color=S.BG_PILL, text_color=S.TEXT_SECONDARY,
            hover_color=S.BG_PILL_HOVER,
            font=S.FONT_TINY,
            corner_radius=S.RADIUS_PILL,
            border_width=0)

    def _set(self, d):
        self._date = d
        self._refresh_chips()
        if self._on_change:
            try:
                self._on_change(d)
            except Exception:
                pass

    def _refresh_chips(self):
        today = date.today()
        # Reset chip styles
        for b in (self.btn_today, self.btn_tom, self.btn_week, self.btn_pick):
            b.configure(fg_color=S.BG_PILL, text_color=S.TEXT_SECONDARY)
        self.btn_pick.configure(text="pick")

        if self._date is None:
            self.btn_clear.pack_forget()
            return

        # Highlight whichever chip matches
        if self._date == today:
            self.btn_today.configure(fg_color=S.ACCENT, text_color="white")
        elif self._date == today + timedelta(days=1):
            self.btn_tom.configure(fg_color=S.ACCENT, text_color="white")
        elif self._date == today + timedelta(days=7):
            self.btn_week.configure(fg_color=S.ACCENT, text_color="white")
        else:
            # Custom date — show it on the pick button
            self.btn_pick.configure(text=self._date.strftime("%d/%m"),
                                    fg_color=S.ACCENT, text_color="white")
        self.btn_clear.pack(side="left", padx=(2, 0))

    def _open_popup(self):
        CalendarPopup(self, initial=self._date, on_pick=self._set)

    def get_date(self):
        return self._date

    def clear(self):
        self._set(None)


# ─────────────────────────────────────────────────────────────────────
# Chip-style selectors — responsive, won't ever crop
# ─────────────────────────────────────────────────────────────────────

class ChipPicker(ctk.CTkFrame):
    """Generic horizontal chip selector. Tap a chip to select.
    Chips share width equally via fill+expand."""

    def __init__(self, parent, options, initial=None, on_change=None):
        """options: list of (value, label, accent_color, tint_color).
        We name the attribute _chip_opts (NOT _options) because tkinter's
        Frame already defines a private _options method used during pack()."""
        super().__init__(parent, fg_color="transparent")
        self._chip_opts = options
        self._value = initial
        self._on_change = on_change
        self._buttons: dict = {}
        self._build()

    def _build(self):
        for value, label, color, tint in self._chip_opts:
            btn = ctk.CTkButton(
                self, text=label, height=26,
                fg_color=tint, text_color=color,
                hover_color=S.BG_PILL_HOVER,
                font=S.FONT_TINY,
                corner_radius=S.RADIUS_PILL,
                border_width=0,
                command=lambda v=value: self._select(v))
            btn.pack(side="left", fill="x", expand=True, padx=1)
            self._buttons[value] = btn
        self._refresh()

    def _select(self, v):
        self._value = v
        self._refresh()
        if self._on_change:
            try:
                self._on_change(v)
            except Exception:
                pass

    def _refresh(self):
        for value, label, color, tint in self._chip_opts:
            btn = self._buttons.get(value)
            if not btn:
                continue
            if value == self._value:
                btn.configure(fg_color=color, text_color="white",
                              hover_color=color)
            else:
                btn.configure(fg_color=tint, text_color=color,
                              hover_color=S.BG_PILL_HOVER)

    def get_value(self):
        return self._value


# ─────────────────────────────────────────────────────────────────────
# Reusable: Pill (tag chip)
# ─────────────────────────────────────────────────────────────────────

class Pill(ctk.CTkFrame):
    """A small rounded tag chip. Used for category, priority, due-date badges."""

    def __init__(self, parent, text: str, color: str, tint: str,
                 leading: Optional[str] = None):
        super().__init__(parent, fg_color=tint, corner_radius=S.RADIUS_PILL)
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=8, pady=1)
        if leading:
            ctk.CTkLabel(inner, text=leading, text_color=color,
                         font=(S.FONT_FAMILY, 10)).pack(side="left", padx=(0, 3))
        ctk.CTkLabel(inner, text=text, text_color=color,
                     font=S.FONT_TINY).pack(side="left")


# ─────────────────────────────────────────────────────────────────────
# Custom title bar (drag + close + pin toggle)
# ─────────────────────────────────────────────────────────────────────

class TitleBar(ctk.CTkFrame):
    def __init__(self, parent, on_close: Callable, on_toggle_pin: Callable):
        super().__init__(parent, fg_color=S.BG_MAIN, height=S.HEADER_H,
                         corner_radius=0)
        self.parent_window = parent
        self.on_close = on_close
        self.on_toggle_pin = on_toggle_pin
        self._drag_dx = 0
        self._drag_dy = 0
        self._build()

    def _build(self):
        # Subtle handle dots in the middle — discoverable but unobtrusive
        self.handle_lbl = ctk.CTkLabel(self, text="• • •",
                                       font=(S.FONT_FAMILY, 11, "bold"),
                                       text_color=S.TEXT_MUTED)
        self.handle_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # Left: pin/unpin toggle (looks like a small house)
        self.pin_btn = ctk.CTkButton(self, text="⌂", width=26, height=26,
                                     fg_color="transparent",
                                     text_color=S.TEXT_SECONDARY,
                                     hover_color=S.BG_PILL_HOVER,
                                     font=(S.FONT_FAMILY, 13),
                                     corner_radius=S.RADIUS_BUTTON,
                                     command=self.on_toggle_pin)
        self.pin_btn.place(x=8, rely=0.5, anchor="w")

        # Right: close (hide to tray)
        self.close_btn = ctk.CTkButton(self, text="✕", width=26, height=26,
                                       fg_color="transparent",
                                       text_color=S.TEXT_MUTED,
                                       hover_color=S.OVERDUE_TINT,
                                       font=(S.FONT_FAMILY, 11, "bold"),
                                       corner_radius=S.RADIUS_BUTTON,
                                       command=self.on_close)
        self.close_btn.place(relx=1, x=-8, rely=0.5, anchor="e")

        # Drag bindings — frame + handle (NOT on buttons)
        for w in (self, self.handle_lbl):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)

    def _start_drag(self, event):
        self._drag_dx = event.x_root - self.parent_window.winfo_x()
        self._drag_dy = event.y_root - self.parent_window.winfo_y()

    def _on_drag(self, event):
        new_x = event.x_root - self._drag_dx
        new_y = event.y_root - self._drag_dy
        self.parent_window.geometry(f"+{new_x}+{new_y}")

    def _end_drag(self, _event):
        try:
            self.parent_window.save_geometry()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
# Resize grip
# ─────────────────────────────────────────────────────────────────────

class ResizeGrip(tk.Canvas):
    """Bigger, more visible resize grip in the bottom-right corner.
    Drag to resize the (borderless) window."""

    SIZE = 22

    def __init__(self, parent, window):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, bg=S.BG_MAIN)
        self.window = window
        # 6-dot staircase — visible enough to discover
        dots = [
            (4, 18), (10, 18), (16, 18),
            (10, 12), (16, 12),
            (16, 6),
        ]
        for x, y in dots:
            self.create_oval(x, y, x + 3, y + 3,
                             fill=S.TEXT_MUTED, outline="")
        self.configure(cursor="bottom_right_corner")
        self.bind("<ButtonPress-1>", self._start)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._end)
        self._start_w = self._start_h = self._start_x = self._start_y = 0

    def _start(self, event):
        self._start_w = self.window.winfo_width()
        self._start_h = self.window.winfo_height()
        self._start_x = event.x_root
        self._start_y = event.y_root

    def _drag(self, event):
        dw = event.x_root - self._start_x
        dh = event.y_root - self._start_y
        new_w = max(S.WINDOW_MIN_W, self._start_w + dw)
        new_h = max(S.WINDOW_MIN_H, self._start_h + dh)
        # Include current x,y so geometry() doesn't reset position on some platforms
        x = self.window.winfo_x()
        y = self.window.winfo_y()
        self.window.geometry(f"{new_w}x{new_h}+{x}+{y}")
        try:
            self.window.update_idletasks()
        except Exception:
            pass

    def _end(self, _event):
        try:
            self.window.save_geometry()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
# Task Card
# ─────────────────────────────────────────────────────────────────────

class TaskCard(ctk.CTkFrame):
    """Compact task row with subtle white card chrome (visual separation
    from the cream backdrop). Meta info below name in tiny grey text."""

    def __init__(self, parent, task: Task, on_toggle: Callable, on_edit: Callable,
                 on_delete: Callable, archived: bool = False,
                 on_restore: Callable = None):
        super().__init__(parent, fg_color=S.BG_CARD, corner_radius=S.RADIUS_SM)
        self.task = task
        self.on_toggle = on_toggle
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_restore = on_restore
        self.archived = archived
        self._build()

    def _build(self):
        cat_color = S.CATEGORY_COLORS.get(self.task.category, S.ACCENT)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=4, pady=(3, 0))

        check_var = ctk.BooleanVar(value=self.task.completed)
        cb = ctk.CTkCheckBox(
            top, text="", width=18, variable=check_var,
            command=lambda: self.on_toggle(self.task.id),
            fg_color=cat_color, hover_color=cat_color,
            border_color=S.BORDER_MED, border_width=2,
            checkmark_color="white", corner_radius=999,
            checkbox_width=16, checkbox_height=16)
        cb.pack(side="left", padx=(2, 6))

        name_color = S.TEXT_STRIKE if self.task.completed else S.TEXT_PRIMARY
        font = (ctk.CTkFont(family=S.FONT_FAMILY, size=11, overstrike=True)
                if self.task.completed
                else ctk.CTkFont(family=S.FONT_FAMILY, size=11))
        # Default wraplength matches the content area at default window width;
        # MainWindow updates this on resize for live reflow.
        self.name_lbl = ctk.CTkLabel(top, text=self.task.name, anchor="w",
                                     text_color=name_color, font=font,
                                     justify="left", wraplength=240)
        self.name_lbl.pack(side="left", fill="x", expand=True)
        # Make the name clickable to edit
        if not self.archived:
            self.name_lbl.bind("<Button-1>",
                               lambda _e: self.on_edit(self.task.id))
            self.name_lbl.configure(cursor="hand2")

        # Single tiny action on the right — restore (archive) or delete (active)
        action_btn_kwargs = dict(
            width=18, height=18, fg_color="transparent",
            text_color=S.TEXT_MUTED, font=S.FONT_TINY,
            corner_radius=S.RADIUS_SM, border_width=0)
        if self.archived:
            ctk.CTkButton(top, text="↺", hover_color=S.ACCENT_TINT,
                          command=lambda: self.on_restore(self.task.id),
                          **action_btn_kwargs).pack(side="right", padx=(2, 0))
        ctk.CTkButton(top, text="✕", hover_color=S.OVERDUE_TINT,
                      command=lambda: self.on_delete(self.task.id),
                      **action_btn_kwargs).pack(side="right", padx=(2, 0))
        if self.task.gcal_event_id:
            ctk.CTkLabel(top, text="📅",
                         text_color=S.ACCENT,
                         font=(S.FONT_FAMILY, 8)
                         ).pack(side="right", padx=(2, 0))

        # Meta line — tiny grey, only if something to show
        bits = []
        if self.task.due_date:
            try:
                dd = datetime.strptime(self.task.due_date, "%Y-%m-%d").date()
                today_ = date.today()
                if dd == today_:
                    bits.append("today")
                elif dd == today_ + timedelta(days=1):
                    bits.append("tom.")
                elif 0 < (dd - today_).days < 7:
                    bits.append(dd.strftime("%a").lower())
                else:
                    bits.append(dd.strftime("%d/%m"))
            except ValueError:
                pass
        if self.task.priority:
            bits.append(self.task.priority)
        if self.task.reminder_at and not self.archived:
            bits.append("⏰")

        if bits:
            is_overdue = self.task.is_overdue() and not self.archived
            color = S.OVERDUE_TEXT if is_overdue else S.TEXT_MUTED
            meta_text = "  ·  ".join(bits)
            self.meta_lbl = ctk.CTkLabel(self, text=meta_text,
                                         text_color=color,
                                         font=S.FONT_TINY,
                                         anchor="w")
            self.meta_lbl.pack(fill="x", padx=(28, 4), pady=(0, 3))


# ─────────────────────────────────────────────────────────────────────
# Add / Edit Task Dialog
# ─────────────────────────────────────────────────────────────────────

class TaskDialog(ctk.CTkToplevel):
    def __init__(self, parent, store: TodoStore, task: Optional[Task] = None,
                 on_saved: Callable = None):
        super().__init__(parent)
        self.store = store
        self.task = task
        self.on_saved = on_saved
        self.title("Edit task" if task else "New task")
        # Dialog dims (bigger so fields don't get cut)
        dw, dh = 440, 680
        self.geometry(f"{dw}x{dh}")
        self.resizable(True, True)
        self.minsize(380, 500)
        self.configure(fg_color=S.BG_MAIN)
        self.transient(parent)
        self.after(50, self._safe_grab)
        self._build()
        # Position on-screen — centre on parent, clamp to display bounds
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - dw // 2
            y = parent.winfo_rooty() + 50
            x = max(20, min(x, sw - dw - 20))
            y = max(20, min(y, sh - dh - 60))
            self.geometry(f"{dw}x{dh}+{x}+{y}")
        except Exception:
            pass

    def _safe_grab(self):
        try:
            self.grab_set()
        except Exception:
            pass

    def _label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, anchor="w",
                            text_color=S.TEXT_SECONDARY, font=S.FONT_CAPTION)

    def _build(self):
        wrap = ctk.CTkScrollableFrame(
            self, fg_color=S.BG_CARD, corner_radius=S.RADIUS_CARD,
            scrollbar_button_color=S.BORDER_LIGHT,
            scrollbar_button_hover_color=S.TEXT_MUTED)
        wrap.pack(fill="both", expand=True, padx=12, pady=(12, 8))

        # Title
        ctk.CTkLabel(wrap, text=("Edit task" if self.task else "New task"),
                     font=S.FONT_TITLE, anchor="w",
                     text_color=S.TEXT_PRIMARY
                     ).pack(fill="x", padx=16, pady=(14, 12))

        # Name
        self._label(wrap, "TASK NAME").pack(fill="x", padx=16)
        self.name_var = ctk.StringVar(value=self.task.name if self.task else "")
        name_entry = ctk.CTkEntry(wrap, textvariable=self.name_var,
                                  font=S.FONT_BODY, height=38,
                                  fg_color=S.BG_CARD_ALT,
                                  border_color=S.BORDER_LIGHT,
                                  border_width=1,
                                  corner_radius=S.RADIUS_BUTTON,
                                  placeholder_text="What needs doing?")
        name_entry.pack(fill="x", padx=16, pady=(4, 14))
        name_entry.focus_set()

        # Category
        self._label(wrap, "CATEGORY").pack(fill="x", padx=16)
        self.cat_var = ctk.StringVar(value=(self.task.category if self.task else "work"))
        cat_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        cat_frame.pack(fill="x", padx=16, pady=(4, 14))
        for c in S.CATEGORIES:
            ctk.CTkRadioButton(cat_frame, text=S.CATEGORY_LABELS[c],
                               variable=self.cat_var, value=c,
                               font=S.FONT_SMALL,
                               fg_color=S.CATEGORY_COLORS[c],
                               hover_color=S.CATEGORY_COLORS[c],
                               border_color=S.BORDER_MED,
                               text_color=S.TEXT_PRIMARY).pack(side="left", padx=(0, 14))

        # Priority
        self._label(wrap, "PRIORITY (OPTIONAL)").pack(fill="x", padx=16)
        self.prio_var = ctk.StringVar(value=(self.task.priority if self.task and self.task.priority else "none"))
        prio_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        prio_frame.pack(fill="x", padx=16, pady=(4, 14))
        for val, label in [("none", "None"), ("low", "Low"), ("medium", "Med"), ("high", "High")]:
            color = S.PRIORITY_COLORS.get(val, S.TEXT_MUTED)
            ctk.CTkRadioButton(prio_frame, text=label, variable=self.prio_var, value=val,
                               font=S.FONT_SMALL,
                               fg_color=color, hover_color=color,
                               border_color=S.BORDER_MED,
                               text_color=S.TEXT_PRIMARY).pack(side="left", padx=(0, 12))

        # Due date — calendar picker
        self._label(wrap, "DUE DATE (OPTIONAL)").pack(fill="x", padx=16)
        initial_due = None
        if self.task and self.task.due_date:
            try:
                initial_due = datetime.strptime(self.task.due_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        self.due_picker = DatePickerButton(wrap, initial=initial_due,
                                           placeholder="add a due date")
        self.due_picker.pack(fill="x", padx=16, pady=(4, 0))

        # Due time
        self._label(wrap, "DUE TIME (OPTIONAL)").pack(fill="x", padx=16, pady=(10, 0))
        time_row = ctk.CTkFrame(wrap, fg_color="transparent")
        time_row.pack(fill="x", padx=16, pady=(4, 14))
        h, m, ap = time_24h_to_12h(self.task.due_time if self.task else None)
        self.due_hour = ctk.StringVar(value=h)
        self.due_min = ctk.StringVar(value=m)
        self.due_ampm = ctk.StringVar(value=ap)
        cb_kwargs = dict(width=64, height=32,
                         fg_color=S.BG_CARD_ALT, border_color=S.BORDER_LIGHT,
                         button_color=S.ACCENT, button_hover_color=S.ACCENT_HOVER,
                         dropdown_fg_color=S.BG_CARD,
                         dropdown_hover_color=S.ACCENT_TINT,
                         font=S.FONT_SMALL)
        ctk.CTkComboBox(time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.due_hour, **cb_kwargs).pack(side="left")
        ctk.CTkLabel(time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left", padx=2)
        ctk.CTkComboBox(time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.due_min, **cb_kwargs).pack(side="left")
        ctk.CTkComboBox(time_row, values=["AM", "PM"],
                        variable=self.due_ampm, **cb_kwargs).pack(side="left", padx=(6, 6))
        self.use_time_var = ctk.BooleanVar(value=bool(self.task and self.task.due_time))
        ctk.CTkCheckBox(time_row, text="set", variable=self.use_time_var,
                        font=S.FONT_TINY, width=20,
                        fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                        border_color=S.BORDER_MED,
                        text_color=S.TEXT_SECONDARY).pack(side="left")

        # Reminder — calendar picker
        self._label(wrap, "REMIND ME (OPTIONAL)").pack(fill="x", padx=16, pady=(12, 0))
        initial_rem = None
        self.rem_hour = ctk.StringVar(value="9")
        self.rem_min = ctk.StringVar(value="00")
        self.rem_ampm = ctk.StringVar(value="AM")
        if self.task and self.task.reminder_at:
            try:
                rd = datetime.fromisoformat(self.task.reminder_at)
                initial_rem = rd.date()
                hh, mm, ap2 = time_24h_to_12h(f"{rd.hour:02d}:{rd.minute:02d}")
                self.rem_hour.set(hh); self.rem_min.set(mm); self.rem_ampm.set(ap2)
            except ValueError:
                pass
        self.rem_picker = DatePickerButton(wrap, initial=initial_rem,
                                           placeholder="add a reminder date")
        self.rem_picker.pack(fill="x", padx=16, pady=(4, 0))

        rem_time_row = ctk.CTkFrame(wrap, fg_color="transparent")
        rem_time_row.pack(fill="x", padx=16, pady=(4, 18))
        ctk.CTkComboBox(rem_time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.rem_hour, **cb_kwargs).pack(side="left")
        ctk.CTkLabel(rem_time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left", padx=2)
        ctk.CTkComboBox(rem_time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.rem_min, **cb_kwargs).pack(side="left")
        ctk.CTkComboBox(rem_time_row, values=["AM", "PM"],
                        variable=self.rem_ampm, **cb_kwargs).pack(side="left", padx=(6, 0))

        # Action buttons (outside scroll area, fixed at bottom)
        btns = ctk.CTkFrame(self, fg_color=S.BG_MAIN)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btns, text="Cancel", fg_color=S.BG_CARD,
                      text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_CARD_ALT,
                      corner_radius=S.RADIUS_BUTTON, height=38,
                      font=S.FONT_BODY,
                      command=self.destroy
                      ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(btns, text=("Save" if self.task else "Add task"),
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      corner_radius=S.RADIUS_BUTTON, height=38,
                      font=S.FONT_BODY_BOLD,
                      command=self._save
                      ).pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Please enter a task name.",
                                   parent=self)
            return
        category = self.cat_var.get()
        prio = self.prio_var.get()
        priority = None if prio == "none" else prio

        due_date = None
        d = self.due_picker.get_date()
        if d:
            due_date = d.strftime("%Y-%m-%d")

        due_time = None
        if self.use_time_var.get() and due_date:
            t = time_12h_to_24h(self.due_hour.get(), self.due_min.get(),
                                self.due_ampm.get())
            if t:
                due_time = t

        reminder_at = None
        rd = self.rem_picker.get_date()
        if rd:
            t = time_12h_to_24h(self.rem_hour.get(), self.rem_min.get(),
                                self.rem_ampm.get())
            if not t:
                messagebox.showwarning("Bad time", "Invalid reminder time.",
                                       parent=self)
                return
            hh, mm = t.split(":")
            reminder_at = f"{rd.strftime('%Y-%m-%d')}T{hh}:{mm}"

        try:
            if self.task:
                saved = self.store.edit_task(
                    self.task.id, name=name, category=category,
                    priority=priority, due_date=due_date,
                    due_time=due_time, reminder_at=reminder_at)
                is_new = False
            else:
                saved = self.store.add_task(
                    name, category, priority=priority,
                    due_date=due_date, due_time=due_time,
                    reminder_at=reminder_at)
                is_new = True
        except ValueError as e:
            messagebox.showerror("Couldn't save", str(e), parent=self)
            return

        if self.on_saved:
            try:
                self.on_saved(saved, is_new)
            except Exception as e:
                print(f"[ui] on_saved callback failed: {e}", file=sys.stderr)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────
# Inline Quick-Add Row
# ─────────────────────────────────────────────────────────────────────

class NotificationBar(ctk.CTkFrame):
    """Top-of-window notification slot. Surfaces things like 'connect Google
    Calendar' or 'X overdue tasks'. Only renders when there's something to say."""

    def __init__(self, parent, on_connect_gcal):
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.on_connect_gcal = on_connect_gcal
        self._banner = None

    def refresh(self, store):
        if self._banner is not None:
            try:
                self._banner.destroy()
            except Exception:
                pass
            self._banner = None

        status = gcal.setup_status() if gcal.is_library_available() else {"ready": True}
        if not status.get("ready"):
            self._show_connect_gcal()
            return

        overdue = len(store.overdue_tasks())
        if overdue >= 3:
            self._show_overdue_warning(overdue)

    def _make_banner(self, icon: str, message: str, action_label: str,
                     action_cmd, tint: str, text_color: str):
        b = ctk.CTkFrame(self, fg_color=tint, corner_radius=S.RADIUS_CARD)
        b.pack(fill="x")
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(row, text=icon,
                     font=(S.FONT_FAMILY, 12)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text=message, anchor="w",
                     text_color=text_color, font=S.FONT_SMALL
                     ).pack(side="left", fill="x", expand=True)
        if action_label:
            ctk.CTkButton(row, text=action_label, height=26,
                          fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                          text_color="white",
                          corner_radius=S.RADIUS_BUTTON,
                          font=S.FONT_TINY,
                          command=action_cmd).pack(side="right")
        self._banner = b

    def _show_connect_gcal(self):
        self._make_banner(
            icon="🔔",
            message="Connect Google Calendar to see your events",
            action_label="Connect",
            action_cmd=self.on_connect_gcal,
            tint=S.ACCENT_TINT,
            text_color=S.TEXT_ON_TINT,
        )

    def _show_overdue_warning(self, n: int):
        self._make_banner(
            icon="⚠",
            message=f"{n} overdue tasks",
            action_label="",
            action_cmd=None,
            tint=S.OVERDUE_TINT,
            text_color=S.OVERDUE_TEXT,
        )


class GreetingCard(ctk.CTkFrame):
    """Greeting hero — mascot + serif-italic greeting + tagline + stats.
    Persistent across refreshes; update_text() refreshes labels in place."""

    def __init__(self, parent, store):
        super().__init__(parent, fg_color=S.BG_CARD, corner_radius=S.RADIUS_CARD)
        self.store = store
        self._build()

    def _build(self):
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        # Mascot
        mascot_img = _ctk_mascot(56)
        if mascot_img:
            ctk.CTkLabel(inner, image=mascot_img, text=""
                         ).pack(side="left", padx=(0, 14))
        else:
            ctk.CTkLabel(inner, text="✿",
                         font=(S.FONT_FAMILY, 32),
                         text_color=S.ACCENT).pack(side="left", padx=(0, 14))

        text_col = ctk.CTkFrame(inner, fg_color="transparent")
        text_col.pack(side="left", fill="both", expand=True)

        # Serif italic greeting — elegant signature
        self.greet_lbl = ctk.CTkLabel(
            text_col, text="", anchor="w",
            font=S.FONT_DISPLAY,
            text_color=S.TEXT_PRIMARY)
        self.greet_lbl.pack(anchor="w")

        # Tagline in small italic
        self.tagline_lbl = ctk.CTkLabel(
            text_col, text="", anchor="w",
            font=(S.FONT_FAMILY, 10, "italic"),
            text_color=S.TEXT_SECONDARY)
        self.tagline_lbl.pack(anchor="w", pady=(2, 6))

        # Stats line
        self.sub_lbl = ctk.CTkLabel(
            text_col, text="", anchor="w",
            font=S.FONT_TINY, text_color=S.TEXT_MUTED)
        self.sub_lbl.pack(anchor="w")
        self.update_text()

    def update_text(self):
        try:
            now = datetime.now()
            name = self.store.settings.get("user_name", "Rashi")
            greeting, tagline = greeting_for(now, name)
            active_count = len(self.store.active_tasks())
            overdue_count = len(self.store.overdue_tasks())
            parts = []
            if overdue_count:
                parts.append(f"{overdue_count} overdue")
            parts.append(f"{active_count} active")
            parts.append(now.strftime("%A, %d %B"))
            self.greet_lbl.configure(text=greeting)
            self.tagline_lbl.configure(text=tagline)
            self.sub_lbl.configure(text="   ·   ".join(parts),
                                   text_color=(S.OVERDUE_TEXT if overdue_count
                                               else S.TEXT_MUTED))
        except Exception as e:
            print(f"[ui] greeting update failed: {e}", file=sys.stderr)


class QuickAddInline(ctk.CTkFrame):
    """Inline create-task panel with ALL fields. Persistent (state survives
    list refreshes). Collapses to height 1 when not in use, animates open."""

    COLLAPSED_H = 1
    EXPANDED_H = 430

    def __init__(self, parent, store, on_submitted,
                 on_opened=None, on_closed=None):
        super().__init__(parent, fg_color=S.BG_CARD,
                         corner_radius=S.RADIUS_CARD,
                         height=self.COLLAPSED_H)
        self.pack_propagate(False)
        self.store = store
        self.on_submitted = on_submitted
        self.on_opened = on_opened     # fired right after open() is called
        self.on_closed = on_closed     # fired right after close() is called
        self.is_open = False
        self._build_content()

    def _label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, anchor="w",
                            text_color=S.TEXT_MUTED, font=S.FONT_CAPTION)

    def _build_content(self):
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=10)

        # Name row
        self.name_var = ctk.StringVar()
        name_entry = ctk.CTkEntry(
            inner, textvariable=self.name_var,
            placeholder_text="New task…",
            font=S.FONT_BODY, height=34,
            fg_color=S.BG_CARD_ALT, border_color=S.BORDER_LIGHT,
            border_width=1, corner_radius=S.RADIUS_BUTTON)
        name_entry.pack(fill="x")
        name_entry.bind("<Return>", lambda _e: self._submit())
        name_entry.bind("<Escape>", lambda _e: self.close())
        self.name_entry = name_entry

        # Row: category + priority chips
        chip_row = ctk.CTkFrame(inner, fg_color="transparent")
        chip_row.pack(fill="x", pady=(8, 0))
        self._label(chip_row, "CATEGORY").pack(anchor="w")
        cat_frame = ctk.CTkFrame(chip_row, fg_color="transparent")
        cat_frame.pack(fill="x", pady=(2, 0))
        self.cat_var = ctk.StringVar(value="work")
        for c in S.CATEGORIES:
            ctk.CTkRadioButton(cat_frame, text=S.CATEGORY_LABELS[c],
                               variable=self.cat_var, value=c,
                               font=S.FONT_SMALL,
                               fg_color=S.CATEGORY_COLORS[c],
                               hover_color=S.CATEGORY_COLORS[c],
                               border_color=S.BORDER_MED,
                               text_color=S.TEXT_PRIMARY,
                               radiobutton_width=16, radiobutton_height=16
                               ).pack(side="left", padx=(0, 10))

        prio_row = ctk.CTkFrame(inner, fg_color="transparent")
        prio_row.pack(fill="x", pady=(8, 0))
        self._label(prio_row, "PRIORITY").pack(anchor="w")
        prio_frame = ctk.CTkFrame(prio_row, fg_color="transparent")
        prio_frame.pack(fill="x", pady=(2, 0))
        self.prio_var = ctk.StringVar(value="none")
        for val, label in [("none", "—"), ("low", "Low"), ("medium", "Med"), ("high", "High")]:
            color = S.PRIORITY_COLORS.get(val, S.TEXT_MUTED)
            ctk.CTkRadioButton(prio_frame, text=label, variable=self.prio_var,
                               value=val, font=S.FONT_SMALL,
                               fg_color=color, hover_color=color,
                               border_color=S.BORDER_MED,
                               text_color=S.TEXT_PRIMARY,
                               radiobutton_width=16, radiobutton_height=16
                               ).pack(side="left", padx=(0, 10))

        cb = dict(width=54, height=32, fg_color=S.BG_CARD_ALT,
                  border_color=S.BORDER_LIGHT,
                  button_color=S.ACCENT, button_hover_color=S.ACCENT_HOVER,
                  dropdown_fg_color=S.BG_CARD,
                  dropdown_hover_color=S.ACCENT_TINT,
                  font=S.FONT_SMALL)

        # Due — date picker + time dropdowns
        self._label(inner, "DUE").pack(anchor="w", pady=(10, 0))
        due_row = ctk.CTkFrame(inner, fg_color="transparent")
        due_row.pack(fill="x", pady=(3, 0))
        self.due_picker = DatePickerButton(due_row, placeholder="add date")
        self.due_picker.pack(side="left", fill="x", expand=True)

        due_time_row = ctk.CTkFrame(inner, fg_color="transparent")
        due_time_row.pack(fill="x", pady=(4, 0))
        self.due_hour = ctk.StringVar(value="9")
        self.due_min = ctk.StringVar(value="00")
        self.due_ampm = ctk.StringVar(value="AM")
        ctk.CTkComboBox(due_time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.due_hour, **cb).pack(side="left")
        ctk.CTkLabel(due_time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left", padx=2)
        ctk.CTkComboBox(due_time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.due_min, **cb).pack(side="left")
        ctk.CTkComboBox(due_time_row, values=["AM", "PM"],
                        variable=self.due_ampm, **cb).pack(side="left", padx=(4, 0))
        self.use_time_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(due_time_row, text="set time", variable=self.use_time_var,
                        width=20, font=S.FONT_TINY,
                        fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                        border_color=S.BORDER_MED,
                        text_color=S.TEXT_SECONDARY
                        ).pack(side="left", padx=(8, 0))

        # Reminder
        self._label(inner, "REMIND ME").pack(anchor="w", pady=(10, 0))
        rem_row = ctk.CTkFrame(inner, fg_color="transparent")
        rem_row.pack(fill="x", pady=(3, 0))
        self.rem_picker = DatePickerButton(rem_row, placeholder="add date")
        self.rem_picker.pack(side="left", fill="x", expand=True)

        rem_time_row = ctk.CTkFrame(inner, fg_color="transparent")
        rem_time_row.pack(fill="x", pady=(4, 0))
        self.rem_hour = ctk.StringVar(value="9")
        self.rem_min = ctk.StringVar(value="00")
        self.rem_ampm = ctk.StringVar(value="AM")
        ctk.CTkComboBox(rem_time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.rem_hour, **cb).pack(side="left")
        ctk.CTkLabel(rem_time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left", padx=2)
        ctk.CTkComboBox(rem_time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.rem_min, **cb).pack(side="left")
        ctk.CTkComboBox(rem_time_row, values=["AM", "PM"],
                        variable=self.rem_ampm, **cb).pack(side="left", padx=(4, 0))

        # Action row
        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(actions, text="Cancel", fg_color=S.BG_CARD_ALT,
                      text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_PILL_HOVER,
                      corner_radius=S.RADIUS_BUTTON, height=32,
                      font=S.FONT_SMALL,
                      command=self.close
                      ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(actions, text="Save task",
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      corner_radius=S.RADIUS_BUTTON, height=32,
                      font=S.FONT_BODY_BOLD,
                      command=self._submit
                      ).pack(side="right", fill="x", expand=True, padx=(4, 0))

    def open(self):
        if self.is_open:
            try:
                self.name_entry.focus_set()
            except Exception:
                pass
            return
        self.is_open = True
        if self.on_opened:
            try:
                self.on_opened()
            except Exception as e:
                print(f"[ui] on_opened callback failed: {e}", file=sys.stderr)
        animate(self, "height", self.COLLAPSED_H, self.EXPANDED_H,
                steps=6, duration_ms=120,
                on_complete=lambda: self._after_open())

    def _after_open(self):
        try:
            self.name_entry.focus_set()
        except Exception:
            pass

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self._reset_fields()
        animate(self, "height", self.EXPANDED_H, self.COLLAPSED_H,
                steps=5, duration_ms=100,
                on_complete=lambda: self._after_close())

    def _after_close(self):
        if self.on_closed:
            try:
                self.on_closed()
            except Exception as e:
                print(f"[ui] on_closed callback failed: {e}", file=sys.stderr)

    def _reset_fields(self):
        try:
            self.name_var.set("")
            self.cat_var.set("work")
            self.prio_var.set("none")
            self.due_picker.clear()
            self.due_hour.set("9"); self.due_min.set("00"); self.due_ampm.set("AM")
            self.use_time_var.set(False)
            self.rem_picker.clear()
            self.rem_hour.set("9"); self.rem_min.set("00"); self.rem_ampm.set("AM")
        except Exception:
            pass

    def _submit(self):
        name = self.name_var.get().strip()
        if not name:
            try:
                self.name_entry.focus_set()
            except Exception:
                pass
            return
        category = self.cat_var.get()
        prio = self.prio_var.get()
        priority = None if prio == "none" else prio

        due_date = None
        d = self.due_picker.get_date()
        if d:
            due_date = d.strftime("%Y-%m-%d")

        due_time = None
        if self.use_time_var.get() and due_date:
            t = time_12h_to_24h(self.due_hour.get(), self.due_min.get(),
                                self.due_ampm.get())
            if t:
                due_time = t

        reminder_at = None
        rd = self.rem_picker.get_date()
        if rd:
            t = time_12h_to_24h(self.rem_hour.get(), self.rem_min.get(),
                                self.rem_ampm.get())
            if not t:
                messagebox.showwarning("Bad time", "Invalid reminder time.",
                                       parent=self.winfo_toplevel())
                return
            hh, mm = t.split(":")
            reminder_at = f"{rd.strftime('%Y-%m-%d')}T{hh}:{mm}"

        try:
            saved = self.store.add_task(name, category, priority=priority,
                                        due_date=due_date, due_time=due_time,
                                        reminder_at=reminder_at)
        except ValueError as e:
            messagebox.showerror("Couldn't save", str(e),
                                 parent=self.winfo_toplevel())
            return

        self.close()
        try:
            self.on_submitted(saved)
        except Exception as e:
            print(f"[ui] quick-add callback failed: {e}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────

class MainWindow(ctk.CTk):
    """Compact widget shell: header + scrollable content + tab bar.
    Tapping + takes the entire content area for the create form (no popup)."""

    def __init__(self, store: TodoStore):
        super().__init__()
        self.store = store
        self.title(S.APP_NAME)
        self.configure(fg_color=S.BG_MAIN)
        self.minsize(S.WINDOW_MIN_W, S.WINDOW_MIN_H)

        self.mode = "list"              # 'list' or 'create'
        self.current_view = "active"    # 'active' | 'news' | 'archive'
        self.sort_mode = "proximity"
        self.is_pinned = False
        self.is_hidden = False
        self._editing_task: Optional[Task] = None
        self._news_cache: Optional[tuple] = None
        self._news_loading = False
        self._gcal_events: Optional[list] = None
        self._gcal_window = "today"
        self._gcal_loading = False
        self._gcal_fetched_at: Optional[datetime] = None

        self._restore_geometry()
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        # Responsive layout — reflow labels when the user resizes
        self._last_wrap = 0
        self.bind("<Configure>", self._on_window_resize)

        self._build()
        self._render()

        self.after(250, self._apply_capture_exclusion)
        self.after(1500, lambda: self._fetch_news(force=False))
        self.after(2500, lambda: self._fetch_gcal(self._gcal_window, force=False))
        self.after(300_000, self._periodic_tick)

    # ── Geometry persistence
    def _restore_geometry(self):
        s = self.store.settings
        w = s.get("window_w") or S.WINDOW_W
        h = s.get("window_h") or S.WINDOW_H
        # Sanity clamp — older versions persisted a much larger default.
        # If the saved size is more than 2x the current default, treat it
        # as stale and fall back. Same for ridiculously small values.
        if w > S.WINDOW_W * 2 or w < S.WINDOW_MIN_W:
            w = S.WINDOW_W
            self.store.update_setting("window_w", None)
        if h > S.WINDOW_H * 2 or h < S.WINDOW_MIN_H:
            h = S.WINDOW_H
            self.store.update_setting("window_h", None)
        x = s.get("window_x")
        y = s.get("window_y")
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        if x is None or y is None or not (0 <= x < sw - 80) or not (0 <= y < sh - 80):
            x = sw - w - 24
            y = max(40, (sh - h) // 2 - 40)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def save_geometry(self):
        try:
            self.update_idletasks()
            self.store.update_setting("window_w", self.winfo_width())
            self.store.update_setting("window_h", self.winfo_height())
            self.store.update_setting("window_x", self.winfo_x())
            self.store.update_setting("window_y", self.winfo_y())
        except Exception:
            pass

    # ── Build the static chrome
    def _build(self):
        # Top header (re-rendered by _render_header on mode change)
        self.header = ctk.CTkFrame(self, fg_color=S.BG_MAIN,
                                   height=S.HEADER_H, corner_radius=0)
        self.header.pack(side="top", fill="x")
        self.header.pack_propagate(False)

        # Bottom tab bar — buttons share horizontal space equally
        self.tab_bar = ctk.CTkFrame(self, fg_color=S.BG_CARD,
                                    height=S.TAB_BAR_H, corner_radius=0)
        self.tab_bar.pack(side="bottom", fill="x")
        self.tab_bar.pack_propagate(False)
        divider = ctk.CTkFrame(self, fg_color=S.DIVIDER, height=1)
        divider.pack(side="bottom", fill="x")
        self._build_tab_bar()

        # Scrollable content (everything else)
        self.content = ctk.CTkScrollableFrame(
            self, fg_color=S.BG_MAIN, corner_radius=0,
            scrollbar_button_color=S.BORDER_LIGHT,
            scrollbar_button_hover_color=S.TEXT_MUTED)
        self.content.pack(fill="both", expand=True, padx=8, pady=2)

    def _build_tab_bar(self):
        self.tab_buttons = {}
        for k, label in [("active", "Tasks"), ("news", "News"), ("archive", "Done")]:
            btn = ctk.CTkButton(
                self.tab_bar, text=label,
                height=S.TAB_BAR_H, font=S.FONT_SMALL,
                fg_color="transparent",
                text_color=S.TEXT_SECONDARY,
                hover_color=S.BG_CARD_ALT,
                corner_radius=0, border_width=0,
                command=lambda kk=k: self._set_view(kk))
            btn.pack(side="left", fill="both", expand=True)
            self.tab_buttons[k] = btn

    def _update_tab_styles(self):
        for k, btn in self.tab_buttons.items():
            if k == self.current_view and self.mode == "list":
                btn.configure(fg_color=S.ACCENT_TINT,
                              text_color=S.ACCENT,
                              hover_color=S.ACCENT_TINT,
                              font=S.FONT_BODY_BOLD)
            else:
                btn.configure(fg_color="transparent",
                              text_color=S.TEXT_SECONDARY,
                              hover_color=S.BG_CARD_ALT,
                              font=S.FONT_SMALL)

    # ── Header
    def _render_header(self):
        for w in list(self.header.winfo_children()):
            try: w.destroy()
            except Exception: pass

        if self.mode == "create":
            self._render_header_create()
        else:
            self._render_header_list()

    def _render_header_list(self):
        # Mascot on the left
        mascot = _ctk_mascot(24)
        if mascot:
            ctk.CTkLabel(self.header, image=mascot, text=""
                         ).pack(side="left", padx=(10, 6))
        else:
            ctk.CTkLabel(self.header, text="✿", text_color=S.ACCENT,
                         font=(S.FONT_FAMILY, 14)).pack(side="left", padx=(10, 6))

        titles = {"active": "today", "news": "news", "archive": "done"}
        title = titles.get(self.current_view, "today")
        if self.current_view == "active":
            title += f"  ·  {len(self.store.active_tasks())}"
        elif self.current_view == "archive":
            title += f"  ·  {len(self.store.archived_tasks())}"
        ctk.CTkLabel(self.header, text=title,
                     font=(S.FONT_SERIF, 14, "italic"),
                     text_color=S.TEXT_PRIMARY, anchor="w"
                     ).pack(side="left", fill="x", expand=True)

        # Right-side action: + on Tasks, ↻ on News
        if self.current_view == "active":
            ctk.CTkButton(self.header, text="+", width=30, height=26,
                          fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                          text_color="white",
                          font=(S.FONT_FAMILY, 16, "bold"),
                          corner_radius=S.RADIUS_BUTTON,
                          command=self._enter_create_mode
                          ).pack(side="right", padx=8)
        elif self.current_view == "news":
            ctk.CTkButton(self.header, text="↻", width=30, height=26,
                          fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                          text_color="white",
                          font=(S.FONT_FAMILY, 12, "bold"),
                          corner_radius=S.RADIUS_BUTTON,
                          command=lambda: self._fetch_news(force=True)
                          ).pack(side="right", padx=8)

    def _render_header_create(self):
        ctk.CTkButton(self.header, text="cancel", height=26, width=60,
                      fg_color="transparent", text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_CARD_ALT,
                      font=S.FONT_SMALL,
                      corner_radius=S.RADIUS_BUTTON,
                      command=self._exit_create_mode
                      ).pack(side="left", padx=8)
        title = "edit task" if self._editing_task else "new task"
        ctk.CTkLabel(self.header, text=title,
                     font=(S.FONT_SERIF, 13, "italic"),
                     text_color=S.TEXT_PRIMARY, anchor="center"
                     ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.header, text="save", height=26, width=58,
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      font=S.FONT_BODY_BOLD,
                      corner_radius=S.RADIUS_BUTTON,
                      command=self._save_from_form
                      ).pack(side="right", padx=8)

    # ── Render entry point
    def _render(self):
        for w in list(self.content.winfo_children()):
            try: w.destroy()
            except Exception: pass

        try:
            if self.mode == "create":
                self._render_create_form()
            elif self.current_view == "active":
                self._render_active()
            elif self.current_view == "news":
                self._render_news()
            else:
                self._render_archive()
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            try:
                err = ctk.CTkFrame(self.content, fg_color=S.OVERDUE_TINT,
                                   corner_radius=S.RADIUS_CARD)
                err.pack(fill="x", pady=10, padx=4)
                ctk.CTkLabel(err, text=f"render error: {e}",
                             text_color=S.OVERDUE_TEXT, font=S.FONT_SMALL,
                             wraplength=260, justify="left"
                             ).pack(padx=12, pady=10)
            except Exception:
                pass

        try:
            self.content._parent_canvas.yview_moveto(0)
        except Exception:
            pass

        self._render_header()
        self._update_tab_styles()

    # Backwards-compat alias for callers that still say refresh()
    def refresh(self):
        self._render()

    # ── Modes
    def _set_view(self, view: str):
        if self.mode == "create":
            self.mode = "list"
            self._editing_task = None
        self.current_view = view
        self._render()

    def _enter_create_mode(self):
        if self.current_view != "active":
            self.current_view = "active"
        self._editing_task = None
        self.mode = "create"
        self._render()

    def _enter_edit_mode(self, task_id):
        t = self.store.get_task(task_id)
        if not t:
            return
        self._editing_task = t
        self.mode = "create"
        self._render()

    def _exit_create_mode(self):
        self.mode = "list"
        self._editing_task = None
        self._render()

    def _periodic_tick(self):
        if self.mode == "list" and self.current_view == "active":
            self._render()
        self.after(300_000, self._periodic_tick)

    def _on_window_resize(self, event):
        # Only react to root-window resizes (not children)
        if event.widget is not self:
            return
        # Compute wraplength: window width minus checkbox + actions + padding
        new_wrap = max(60, event.width - 80)
        if abs(new_wrap - self._last_wrap) < 8:
            return
        self._last_wrap = new_wrap
        for child in self.content.winfo_children():
            if isinstance(child, TaskCard) and hasattr(child, "name_lbl"):
                try:
                    child.name_lbl.configure(wraplength=new_wrap)
                except Exception:
                    pass
            # News headline cards have wrapped labels too
            for sub in child.winfo_children() if hasattr(child, "winfo_children") else []:
                if isinstance(sub, ctk.CTkLabel):
                    try:
                        if sub.cget("wraplength") and int(sub.cget("wraplength")) > 0:
                            sub.configure(wraplength=new_wrap)
                    except Exception:
                        pass

    # ── Section header — bigger italic serif, count chip on the right
    def _section_header(self, text, color, count=None):
        bar = ctk.CTkFrame(self.content, fg_color="transparent")
        bar.pack(fill="x", pady=(16, 4), padx=4)
        ctk.CTkLabel(bar, text=text.lower(),
                     font=(S.FONT_SERIF, 15, "italic"),
                     text_color=color, anchor="w"
                     ).pack(side="left", fill="x", expand=True)
        if count is not None:
            ctk.CTkLabel(bar, text=str(count),
                         font=S.FONT_CAPTION, text_color=S.TEXT_MUTED,
                         width=24
                         ).pack(side="right", padx=4)

    def _empty_state(self, message, sub=None):
        wrap = ctk.CTkFrame(self.content, fg_color="transparent")
        wrap.pack(fill="x", pady=30)
        m = _ctk_mascot(48)
        if m:
            ctk.CTkLabel(wrap, image=m, text="").pack()
        else:
            ctk.CTkLabel(wrap, text="✿", text_color=S.ACCENT,
                         font=(S.FONT_FAMILY, 28)).pack()
        ctk.CTkLabel(wrap, text=message, text_color=S.TEXT_PRIMARY,
                     font=(S.FONT_SERIF, 13, "italic")
                     ).pack(pady=(10, 2))
        if sub:
            ctk.CTkLabel(wrap, text=sub, text_color=S.TEXT_MUTED,
                         font=S.FONT_SMALL).pack()

    def _render_card(self, task, archived):
        card = TaskCard(self.content, task,
                        on_toggle=self._toggle,
                        on_edit=self._enter_edit_mode,
                        on_delete=self._confirm_delete,
                        archived=archived,
                        on_restore=self._restore)
        card.pack(fill="x", pady=2, padx=2)
        # Apply current wraplength to the freshly-built card
        if self._last_wrap > 0:
            try:
                card.name_lbl.configure(wraplength=self._last_wrap)
            except Exception:
                pass

    # ── Active view — stripped to just tasks + section headers
    def _render_active(self):
        # GCal connect banner only when actually needed
        if gcal.is_library_available() and not gcal.setup_status()["ready"]:
            self._render_connect_gcal_banner()

        active = self.store.active_tasks()
        if not active:
            msg = S.EMPTY_STATE_MESSAGES[datetime.now().day % len(S.EMPTY_STATE_MESSAGES)]
            self._empty_state(msg, "tap + to add a task")
            return

        groups = TodoStore.group_by_due_proximity(active)
        group_colors = {
            "Overdue":  S.OVERDUE_TEXT,
            "Today":    S.ACCENT,
            "Tomorrow": S.CATEGORY_COLORS["learning"],
            "This week": S.CATEGORY_COLORS["personal"],
            "Later":    S.TEXT_SECONDARY,
            "Someday":  S.TEXT_MUTED,
        }
        for name in TodoStore.PROXIMITY_GROUPS:
            tasks = groups.get(name, [])
            if not tasks:
                continue
            self._section_header(name, group_colors[name], len(tasks))
            for t in tasks:
                self._render_card(t, archived=False)
        ctk.CTkFrame(self.content, height=8, fg_color="transparent"
                     ).pack(fill="x")

    def _render_connect_gcal_banner(self):
        b = ctk.CTkFrame(self.content, fg_color=S.ACCENT_TINT,
                         corner_radius=S.RADIUS_CARD)
        b.pack(fill="x", padx=2, pady=(2, 4))
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(row, text="🔔", font=(S.FONT_FAMILY, 10)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text="connect google calendar",
                     text_color=S.TEXT_ON_TINT, font=S.FONT_SMALL,
                     anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="connect", height=22,
                      fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                      text_color="white",
                      font=S.FONT_TINY,
                      corner_radius=S.RADIUS_BUTTON,
                      command=self._open_gcal_setup).pack(side="right")

    def _render_overdue_banner(self, n):
        b = ctk.CTkFrame(self.content, fg_color=S.OVERDUE_TINT,
                         corner_radius=S.RADIUS_CARD)
        b.pack(fill="x", padx=2, pady=(2, 4))
        ctk.CTkLabel(b, text=f"⚠  {n} overdue tasks",
                     text_color=S.OVERDUE_TEXT, font=S.FONT_SMALL,
                     anchor="w").pack(fill="x", padx=12, pady=8)

    def _render_calendar_events(self):
        if not gcal.is_library_available():
            return
        if not gcal.setup_status()["ready"]:
            return
        if self._gcal_loading and self._gcal_events is None:
            return
        events = self._gcal_events or []
        if not events:
            return
        card = ctk.CTkFrame(self.content, fg_color=S.BG_CARD,
                            corner_radius=S.RADIUS_CARD)
        card.pack(fill="x", padx=2, pady=(2, 4))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 2))
        title = "today's events" if self._gcal_window == "today" else "this week"
        ctk.CTkLabel(head, text=title, font=S.FONT_CAPTION,
                     text_color=S.TEXT_MUTED).pack(side="left")
        toggle_lbl = "week" if self._gcal_window == "today" else "today"
        ctk.CTkButton(head, text=toggle_lbl, width=44, height=20,
                      fg_color="transparent", text_color=S.TEXT_SECONDARY,
                      hover_color=S.BG_CARD_ALT,
                      font=S.FONT_TINY,
                      corner_radius=S.RADIUS_PILL,
                      command=self._toggle_gcal_window).pack(side="right")
        for ev in events[:4]:
            self._render_event_row(card, ev)
        if len(events) > 4:
            ctk.CTkLabel(card, text=f"+{len(events) - 4} more",
                         text_color=S.TEXT_MUTED, font=S.FONT_TINY
                         ).pack(padx=12, pady=(2, 6))
        ctk.CTkFrame(card, height=4, fg_color="transparent").pack(fill="x")

    def _render_event_row(self, parent, event):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row, text="●",
                     text_color=event.get("calendar_color") or S.ACCENT,
                     font=(S.FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        time_text = self._format_event_time(event)
        ctk.CTkLabel(row, text=time_text, text_color=S.TEXT_SECONDARY,
                     font=S.FONT_TINY, width=64, anchor="w").pack(side="left")
        url = event.get("html_link")
        title_text = event.get("title", "(no title)")
        if url:
            lbl = ctk.CTkLabel(row, text=title_text, text_color=S.TEXT_PRIMARY,
                               font=S.FONT_SMALL, anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            lbl.bind("<Button-1>", lambda _e, u=url: webbrowser.open_new_tab(u))
            lbl.configure(cursor="hand2")
        else:
            ctk.CTkLabel(row, text=title_text, text_color=S.TEXT_PRIMARY,
                         font=S.FONT_SMALL, anchor="w"
                         ).pack(side="left", fill="x", expand=True)

    def _format_event_time(self, event):
        if event.get("all_day"):
            try:
                d = datetime.strptime(event["start"], "%Y-%m-%d").date()
                if d == date.today():
                    return "all day"
                return d.strftime("%d/%m")
            except (ValueError, TypeError):
                return "all day"
        s = event.get("start", "")
        if not s:
            return ""
        try:
            ss = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ss)
            if dt.tzinfo:
                dt = dt.astimezone(tz=None).replace(tzinfo=None)
            if dt.date() == date.today():
                return dt.strftime("%I:%M%p").lstrip("0").lower()
            return dt.strftime("%d/%m %I:%M%p").lstrip("0").lower()
        except (ValueError, TypeError):
            return s[:16] if s else ""

    def _toggle_gcal_window(self):
        self._gcal_window = "week" if self._gcal_window == "today" else "today"
        self._gcal_events = None
        self._fetch_gcal(self._gcal_window, force=False)
        self._render()

    # ── Archive
    def _render_archive(self):
        archived = self.store.archived_tasks()
        if not archived:
            self._empty_state("nothing yet", "completed tasks land here")
            return
        bar = ctk.CTkFrame(self.content, fg_color="transparent")
        bar.pack(fill="x", pady=(2, 4), padx=4)
        ctk.CTkLabel(bar, text=f"{len(archived)} completed",
                     text_color=S.TEXT_SECONDARY, font=S.FONT_SMALL
                     ).pack(side="left")
        ctk.CTkButton(bar, text="clear all", height=22,
                      fg_color="transparent",
                      text_color=S.OVERDUE_TEXT, hover_color=S.OVERDUE_TINT,
                      font=S.FONT_SMALL,
                      corner_radius=S.RADIUS_PILL,
                      command=self._confirm_clear_archive
                      ).pack(side="right")
        archived.sort(key=lambda t: t.completed_at or "", reverse=True)
        for t in archived:
            self._render_card(t, archived=True)

    # ── News
    def _render_news(self):
        if self._news_cache is None and not self._news_loading:
            self._fetch_news(force=False)
            self._render_news_loading()
            return
        if self._news_loading and self._news_cache is None:
            self._render_news_loading()
            return
        headlines, fetched_at, was_fresh = (self._news_cache or ([], None, False))
        if fetched_at:
            txt = "updated " + fetched_at.strftime("%I:%M %p").lstrip("0").lower()
            if not was_fresh:
                txt += "  ·  cached"
            ctk.CTkLabel(self.content, text=txt,
                         text_color=S.TEXT_MUTED, font=S.FONT_TINY,
                         anchor="w").pack(fill="x", padx=4, pady=(2, 4))
        if not headlines:
            self._empty_state("no headlines", "check your connection")
            return
        for h in headlines:
            self._render_headline_card(h)

    def _render_news_loading(self):
        wrap = ctk.CTkFrame(self.content, fg_color="transparent")
        wrap.pack(fill="x", pady=30)
        ctk.CTkLabel(wrap, text="◯", text_color=S.ACCENT,
                     font=(S.FONT_FAMILY, 18)).pack()
        ctk.CTkLabel(wrap, text="fetching today's tech…",
                     text_color=S.TEXT_SECONDARY, font=S.FONT_SMALL
                     ).pack(pady=(8, 0))

    def _render_headline_card(self, headline):
        card = ctk.CTkFrame(self.content, fg_color=S.BG_CARD,
                            corner_radius=S.RADIUS_CARD)
        card.pack(fill="x", pady=4, padx=2)
        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(10, 1))
        ctk.CTkLabel(meta, text=headline.source.lower(),
                     text_color=S.ACCENT, font=S.FONT_CAPTION
                     ).pack(side="left")
        when = self._time_ago(headline.timestamp)
        if when:
            ctk.CTkLabel(meta, text="  ·  " + when,
                         text_color=S.TEXT_MUTED, font=S.FONT_TINY
                         ).pack(side="left")
        title_lbl = ctk.CTkLabel(card, text=headline.title, anchor="w",
                                  text_color=S.TEXT_PRIMARY,
                                  font=S.FONT_BODY_BOLD, justify="left",
                                  wraplength=270)
        title_lbl.pack(fill="x", padx=12, pady=(2, 2))
        title_lbl.bind("<Button-1>",
                       lambda _e, u=headline.url: webbrowser.open_new_tab(u))
        title_lbl.configure(cursor="hand2")
        if headline.description:
            desc_lbl = ctk.CTkLabel(card, text=headline.description, anchor="w",
                                     text_color=S.TEXT_SECONDARY,
                                     font=S.FONT_SMALL, justify="left",
                                     wraplength=270)
            desc_lbl.pack(fill="x", padx=12, pady=(0, 10))
            desc_lbl.bind("<Button-1>",
                          lambda _e, u=headline.url: webbrowser.open_new_tab(u))
            desc_lbl.configure(cursor="hand2")
        else:
            ctk.CTkFrame(card, height=8, fg_color="transparent").pack(fill="x")

    def _time_ago(self, ts):
        if not ts:
            return ""
        try:
            seconds = int(datetime.now().timestamp() - ts)
        except (TypeError, ValueError):
            return ""
        if seconds < 60: return "now"
        m = seconds // 60
        if m < 60: return f"{m}m"
        h = m // 60
        if h < 24: return f"{h}h"
        d = h // 24
        if d < 30: return f"{d}d"
        return ""

    # ── Create / Edit form (takes over the content area)
    def _render_create_form(self):
        editing = self._editing_task

        ctk.CTkLabel(self.content, text="TASK", anchor="w",
                     text_color=S.TEXT_MUTED, font=S.FONT_CAPTION
                     ).pack(fill="x", padx=4, pady=(2, 2))
        self.form_name = ctk.StringVar(value=(editing.name if editing else ""))
        name_entry = ctk.CTkEntry(self.content, textvariable=self.form_name,
                                   placeholder_text="what needs doing?",
                                   font=S.FONT_BODY, height=36,
                                   fg_color=S.BG_CARD,
                                   border_color=S.BORDER_LIGHT,
                                   corner_radius=S.RADIUS_BUTTON)
        name_entry.pack(fill="x", padx=4)
        name_entry.bind("<Return>", lambda _e: self._save_from_form())
        name_entry.bind("<Escape>", lambda _e: self._exit_create_mode())
        try:
            name_entry.focus_set()
        except Exception:
            pass

        ctk.CTkLabel(self.content, text="CATEGORY", anchor="w",
                     text_color=S.TEXT_MUTED, font=S.FONT_CAPTION
                     ).pack(fill="x", padx=4, pady=(12, 3))
        cat_options = [(c, S.CATEGORY_LABELS[c],
                        S.CATEGORY_COLORS[c], S.CATEGORY_TINTS[c])
                       for c in S.CATEGORIES]
        self.form_cat_picker = ChipPicker(
            self.content, options=cat_options,
            initial=(editing.category if editing else "work"))
        self.form_cat_picker.pack(fill="x", padx=4)

        ctk.CTkLabel(self.content, text="PRIORITY", anchor="w",
                     text_color=S.TEXT_MUTED, font=S.FONT_CAPTION
                     ).pack(fill="x", padx=4, pady=(10, 3))
        prio_options = [
            ("none", "—", S.TEXT_SECONDARY, S.BG_PILL),
            ("low", "low", S.PRIORITY_COLORS["low"], S.PRIORITY_TINTS["low"]),
            ("medium", "med", S.PRIORITY_COLORS["medium"], S.PRIORITY_TINTS["medium"]),
            ("high", "high", S.PRIORITY_COLORS["high"], S.PRIORITY_TINTS["high"]),
        ]
        self.form_prio_picker = ChipPicker(
            self.content, options=prio_options,
            initial=(editing.priority if editing and editing.priority else "none"))
        self.form_prio_picker.pack(fill="x", padx=4)

        ctk.CTkLabel(self.content, text="DUE DATE", anchor="w",
                     text_color=S.TEXT_MUTED, font=S.FONT_CAPTION
                     ).pack(fill="x", padx=4, pady=(8, 2))
        initial_due = None
        if editing and editing.due_date:
            try:
                initial_due = datetime.strptime(editing.due_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        self.form_due_picker = QuickDatePicker(self.content, initial=initial_due)
        self.form_due_picker.pack(fill="x", padx=4)

        h, m, ap = time_24h_to_12h(editing.due_time if editing else None)
        self.form_due_hour = ctk.StringVar(value=h)
        self.form_due_min = ctk.StringVar(value=m)
        self.form_due_ampm = ctk.StringVar(value=ap)
        self.form_use_time = ctk.BooleanVar(value=bool(editing and editing.due_time))
        cb = dict(height=26, fg_color=S.BG_CARD,
                  border_color=S.BORDER_LIGHT,
                  button_color=S.ACCENT, button_hover_color=S.ACCENT_HOVER,
                  dropdown_fg_color=S.BG_CARD,
                  dropdown_hover_color=S.ACCENT_TINT,
                  font=S.FONT_TINY)
        due_time_row = ctk.CTkFrame(self.content, fg_color="transparent")
        due_time_row.pack(fill="x", padx=4, pady=(3, 0))
        ctk.CTkComboBox(due_time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.form_due_hour, **cb
                        ).pack(side="left", fill="x", expand=True, padx=1)
        ctk.CTkLabel(due_time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left")
        ctk.CTkComboBox(due_time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.form_due_min, **cb
                        ).pack(side="left", fill="x", expand=True, padx=1)
        ctk.CTkComboBox(due_time_row, values=["AM", "PM"],
                        variable=self.form_due_ampm, **cb
                        ).pack(side="left", fill="x", expand=True, padx=1)
        ctk.CTkCheckBox(due_time_row, text="set",
                        variable=self.form_use_time,
                        width=20, font=S.FONT_TINY,
                        fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                        border_color=S.BORDER_MED,
                        text_color=S.TEXT_SECONDARY,
                        checkbox_width=14, checkbox_height=14
                        ).pack(side="left", padx=(4, 0))

        ctk.CTkLabel(self.content, text="REMIND ME", anchor="w",
                     text_color=S.TEXT_MUTED, font=S.FONT_CAPTION
                     ).pack(fill="x", padx=4, pady=(10, 2))
        initial_rem = None
        h2, m2, ap2 = ("9", "00", "AM")
        if editing and editing.reminder_at:
            try:
                rd = datetime.fromisoformat(editing.reminder_at)
                initial_rem = rd.date()
                h2, m2, ap2 = time_24h_to_12h(f"{rd.hour:02d}:{rd.minute:02d}")
            except ValueError:
                pass
        self.form_rem_picker = QuickDatePicker(self.content, initial=initial_rem)
        self.form_rem_picker.pack(fill="x", padx=4)
        self.form_rem_hour = ctk.StringVar(value=h2)
        self.form_rem_min = ctk.StringVar(value=m2)
        self.form_rem_ampm = ctk.StringVar(value=ap2)
        rem_time_row = ctk.CTkFrame(self.content, fg_color="transparent")
        rem_time_row.pack(fill="x", padx=4, pady=(4, 12))
        ctk.CTkComboBox(rem_time_row, values=[str(i) for i in range(1, 13)],
                        variable=self.form_rem_hour, **cb).pack(side="left")
        ctk.CTkLabel(rem_time_row, text=":", font=S.FONT_BODY,
                     text_color=S.TEXT_SECONDARY).pack(side="left", padx=2)
        ctk.CTkComboBox(rem_time_row, values=[f"{i:02d}" for i in range(0, 60, 5)],
                        variable=self.form_rem_min, **cb).pack(side="left")
        ctk.CTkComboBox(rem_time_row, values=["AM", "PM"],
                        variable=self.form_rem_ampm, **cb).pack(side="left", padx=(4, 0))

    def _save_from_form(self):
        name = (self.form_name.get() if hasattr(self, "form_name") else "").strip()
        if not name:
            return
        category = self.form_cat_picker.get_value()
        prio = self.form_prio_picker.get_value()
        priority = None if prio == "none" else prio

        due_date = None
        d = self.form_due_picker.get_date()
        if d:
            due_date = d.strftime("%Y-%m-%d")
        due_time = None
        if self.form_use_time.get() and due_date:
            t = time_12h_to_24h(self.form_due_hour.get(), self.form_due_min.get(),
                                self.form_due_ampm.get())
            if t:
                due_time = t

        reminder_at = None
        rd = self.form_rem_picker.get_date()
        if rd:
            t = time_12h_to_24h(self.form_rem_hour.get(), self.form_rem_min.get(),
                                self.form_rem_ampm.get())
            if t:
                hh, mm = t.split(":")
                reminder_at = f"{rd.strftime('%Y-%m-%d')}T{hh}:{mm}"

        try:
            if self._editing_task:
                saved = self.store.edit_task(self._editing_task.id,
                                             name=name, category=category,
                                             priority=priority,
                                             due_date=due_date, due_time=due_time,
                                             reminder_at=reminder_at)
                is_new = False
            else:
                saved = self.store.add_task(name, category, priority=priority,
                                            due_date=due_date, due_time=due_time,
                                            reminder_at=reminder_at)
                is_new = True
        except ValueError as e:
            messagebox.showerror("couldn't save", str(e), parent=self)
            return

        self._editing_task = None
        self.mode = "list"
        self._render()
        if saved and saved.due_date:
            if is_new or not saved.gcal_event_id:
                self._sync_push_task(saved)
            else:
                self._sync_update_task(saved)
        elif saved and saved.gcal_event_id:
            self._sync_delete_event(saved)

    # ── News fetch
    def _fetch_news(self, force=False):
        if self._news_loading:
            return
        self._news_loading = True
        if self.mode == "list" and self.current_view == "news":
            for c in list(self.content.winfo_children()):
                try: c.destroy()
                except Exception: pass
            self._render_news_loading()

        def worker():
            try:
                headlines, ts, was_fresh = news_mod.get_news(force_refresh=force)
            except Exception as e:
                print(f"[news] worker failed: {e}", file=sys.stderr)
                headlines, ts, was_fresh = [], None, False
            try:
                self.after(0, lambda: self._news_done(headlines, ts, was_fresh))
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _news_done(self, headlines, ts, was_fresh):
        self._news_cache = (headlines, ts, was_fresh)
        self._news_loading = False
        if self.mode == "list" and self.current_view == "news":
            self._render()

    # ── GCal fetch
    def _fetch_gcal(self, window, force=False):
        if not gcal.is_library_available():
            return
        if not gcal.setup_status()["ready"]:
            return
        if self._gcal_loading:
            return
        self._gcal_loading = True

        def worker():
            try:
                events = (gcal.events_this_week() if window == "week"
                          else gcal.events_today())
                ts = gcal.save_cache(events, window) if events else datetime.now()
            except Exception as e:
                print(f"[gcal] fetch failed: {e}", file=sys.stderr)
                cached, ts_c, _ = gcal.load_cache()
                events, ts = cached, ts_c
            try:
                self.after(0, lambda: self._gcal_done(events, ts, window))
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _gcal_done(self, events, ts, window):
        if window == self._gcal_window:
            self._gcal_events = events
            self._gcal_fetched_at = ts
        self._gcal_loading = False
        if self.mode == "list" and self.current_view == "active":
            self._render()

    def _open_gcal_setup(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("connect google calendar")
        dlg.geometry("540x440")
        dlg.configure(fg_color=S.BG_MAIN)
        dlg.transient(self)
        dlg.after(50, lambda: dlg.grab_set() if dlg.winfo_exists() else None)
        wrap = ctk.CTkFrame(dlg, fg_color=S.BG_CARD, corner_radius=S.RADIUS_CARD)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(wrap, text="connect google calendar",
                     font=S.FONT_TITLE, anchor="w",
                     text_color=S.TEXT_PRIMARY).pack(fill="x", padx=16, pady=(14, 8))
        status = gcal.setup_status()
        steps = []
        if not status["library_installed"]:
            steps.append("install google libraries first:")
            steps.append("  python -m pip install google-auth google-auth-oauthlib google-api-python-client")
            steps.append("")
        if not status["credentials_present"]:
            steps.append("1. go to console.cloud.google.com")
            steps.append("2. create a project (or pick existing)")
            steps.append("3. APIs & Services → Enable APIs → 'Google Calendar API'")
            steps.append("4. Credentials → Create Credentials → OAuth client ID")
            steps.append("   → application type: 'Desktop app' → Create")
            steps.append("5. download the JSON, rename to credentials.json,")
            steps.append(f"   place in: {Path(__file__).resolve().parent}")
            steps.append("6. click authorize below")
        elif not status["token_present"]:
            steps.append("found credentials.json. click authorize to sign in.")
        text = "\n".join(steps) if steps else "everything's connected"
        body = ctk.CTkTextbox(wrap, font=S.FONT_SMALL,
                              fg_color=S.BG_CARD_ALT, text_color=S.TEXT_PRIMARY,
                              wrap="word", height=260,
                              border_color=S.BORDER_LIGHT,
                              corner_radius=S.RADIUS_BUTTON)
        body.pack(fill="both", expand=True, padx=16, pady=6)
        body.insert("1.0", text)
        body.configure(state="disabled")
        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btns, text="close", fg_color=S.BG_CARD_ALT,
                      text_color=S.TEXT_SECONDARY,
                      hover_color=S.BORDER_LIGHT,
                      corner_radius=S.RADIUS_BUTTON, height=36,
                      command=dlg.destroy).pack(side="left")
        if status["library_installed"] and status["credentials_present"]:
            def _auth():
                ok = gcal.authenticate_interactive()
                if not dlg.winfo_exists():
                    return
                if ok:
                    messagebox.showinfo("connected", "google calendar connected.",
                                        parent=dlg)
                    dlg.destroy()
                    self._fetch_gcal(self._gcal_window, force=True)
                else:
                    messagebox.showerror("failed",
                                         "oauth flow failed. check the console.",
                                         parent=dlg)
            ctk.CTkButton(btns, text="authorize…",
                          fg_color=S.ACCENT, hover_color=S.ACCENT_HOVER,
                          text_color="white",
                          corner_radius=S.RADIUS_BUTTON, height=36,
                          font=S.FONT_BODY_BOLD,
                          command=_auth).pack(side="right")

    # ── Actions
    def _toggle(self, task_id):
        before = self.store.get_task(task_id)
        self.store.toggle_complete(task_id)
        self._render()
        if before and not before.completed and before.gcal_event_id:
            self._sync_delete_event(before)

    def open_add_dialog(self):
        # Tray menu still uses this — opens the inline create form
        self._enter_create_mode()

    def _confirm_delete(self, task_id):
        t = self.store.get_task(task_id)
        if not t:
            return
        if messagebox.askyesno("delete?",
                               f"delete \"{t.name}\"?\n\nthis can't be undone.",
                               parent=self):
            self.store.delete_task(task_id)
            self._render()
            if t.gcal_event_id:
                self._sync_delete_event(t)

    def _restore(self, task_id):
        self.store.unarchive_task(task_id)
        self._render()

    def _confirm_clear_archive(self):
        n = len(self.store.archived_tasks())
        if n == 0:
            return
        if messagebox.askyesno("clear archive?",
                               f"permanently delete all {n} archived tasks?",
                               parent=self):
            for t in self.store.archived_tasks():
                self.store.delete_task(t.id)
            self._render()

    # ── GCal sync helpers
    def _sync_push_task(self, task):
        if not gcal.is_library_available() or not gcal.setup_status()["ready"]:
            return
        def worker():
            try:
                event_id = gcal.push_task(task)
            except Exception as e:
                print(f"[gcal] push error: {e}", file=sys.stderr)
                return
            if event_id:
                try:
                    self.store.edit_task(task.id, gcal_event_id=event_id)
                    self.after(0, self._render)
                except (ValueError, RuntimeError):
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def _sync_update_task(self, task):
        if not gcal.is_library_available() or not gcal.setup_status()["ready"]:
            return
        def worker():
            try:
                ok = gcal.update_task_event(task)
            except Exception as e:
                print(f"[gcal] update error: {e}", file=sys.stderr)
                ok = False
            if not ok:
                try:
                    new_id = gcal.push_task(task)
                except Exception as e:
                    print(f"[gcal] re-push error: {e}", file=sys.stderr)
                    return
                if new_id:
                    try:
                        self.store.edit_task(task.id, gcal_event_id=new_id)
                        self.after(0, self._render)
                    except (ValueError, RuntimeError):
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _sync_delete_event(self, task):
        if not gcal.is_library_available() or not gcal.setup_status()["ready"]:
            return
        def worker():
            try:
                gcal.delete_task_event(task)
            except Exception as e:
                print(f"[gcal] delete error: {e}", file=sys.stderr)
        threading.Thread(target=worker, daemon=True).start()

    # ── Windows-level state
    def _hwnd(self):
        return winapi.tk_hwnd(self)

    def _apply_capture_exclusion(self):
        hwnd = self._hwnd()
        if hwnd:
            winapi.exclude_from_capture(hwnd)

    def enter_pinned_mode(self):
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            self.overrideredirect(True)
            self.attributes("-topmost", False)
        except Exception:
            pass
        winapi.pin_to_desktop(hwnd)
        winapi.exclude_from_capture(hwnd)
        self.is_pinned = True

    def enter_floating_mode(self):
        hwnd = self._hwnd()
        if not hwnd:
            return
        winapi.unpin_from_desktop(hwnd)
        try:
            self.overrideredirect(False)
            self.attributes("-topmost", True)
        except Exception:
            pass
        winapi.exclude_from_capture(hwnd)
        winapi.bring_to_front_topmost(hwnd)
        self.is_pinned = False
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def toggle_float(self):
        if self.is_hidden:
            self.toggle_hide()
            return
        if self.is_pinned:
            self.enter_floating_mode()
        else:
            self.enter_pinned_mode()

    def toggle_hide(self):
        if self.is_hidden:
            try:
                self.deiconify()
            except Exception:
                pass
            self.is_hidden = False
            if self.is_pinned:
                self.after(50, self.enter_pinned_mode)
        else:
            try:
                self.withdraw()
            except Exception:
                pass
            self.is_hidden = True

    def hide_to_tray(self):
        try:
            self.withdraw()
        except Exception:
            pass
        self.is_hidden = True



# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def run(store: TodoStore) -> MainWindow:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app = MainWindow(store)
    return app
