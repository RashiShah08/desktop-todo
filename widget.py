"""Floating todo widget — Python backend + HTML/CSS frontend rendered via PyWebView.

Run: python widget.py
 or: pythonw widget.py  (no console, used by the auto-startup shortcut)

The window:
  • Always-on-top floating widget
  • Frameless (the design provides its own title bar)
  • Hidden from screen-share / capture (Windows 10 2004+)
  • Resizable from any edge
  • Closes to system tray (doesn't quit)

All UI rendering lives in `frontend/`. Python owns data, news, GCal, reminders,
hotkeys, and the system-tray icon."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


def _log(msg: str) -> None:
    """Write diagnostics next to the exe.

    The packaged build is compiled with console=False, so stdout/stderr vanish
    and runtime failures are invisible — which is how a drag bug that threw 28
    exceptions per attempt went unnoticed. This gives the frozen app somewhere
    to record what actually happened."""
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(f"[widget] {msg}", file=sys.stderr)
    try:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
            else Path(__file__).resolve().parent
        with open(base / "checkera-debug.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

import webview

# ── Defensive patch: pywebview's drag-region handler can pass float
# coordinates to window.move(), which then trips Win32's SetWindowPos
# (it requires ints). Coerce on the way in so it can never crash.
try:
    import webview.window as _ww
    _orig_move = _ww.Window.move

    def _safe_move(self, x, y):
        return _orig_move(self, int(x), int(y))

    _ww.Window.move = _safe_move
    _orig_resize = _ww.Window.resize
    def _safe_resize(self, w, h, *a, **kw):
        return _orig_resize(self, int(w), int(h), *a, **kw)
    _ww.Window.resize = _safe_resize
except Exception:
    pass

def _patch_winforms_move() -> None:
    """Fix window dragging, which is broken in pywebview 6.2.1 on Windows.

    BrowserView.move (winforms.py:620-644) calls SetWindowPos passing None for
    the cx/cy arguments. SWP_NOSIZE means Windows ignores those values, but
    ctypes still has to marshal them as integers, so every call raises
    ArgumentError before reaching Win32 — 28 tracebacks per drag attempt, and
    the window never moves.

    The target is BrowserView.BrowserForm, the nested Form subclass — NOT
    BrowserView itself, which has no move() at all. The drag bridge dispatches
    winforms.move(x, y, uid) -> BrowserView.instances[uid].move(), and those
    instances are BrowserForm objects, so patching the outer class silently
    does nothing (it just adds an attribute nobody calls)."""
    try:
        import ctypes
        import webview.platforms.winforms as _wf

        def _fixed_move(self, x, y):
            scale = getattr(self, "_scale", 1) or 1
            SWP_NOSIZE, SWP_NOZORDER, SWP_SHOWWINDOW = 0x0001, 0x0004, 0x0040
            ctypes.windll.user32.SetWindowPos(
                self.Handle.ToInt32(), None,
                int(x * scale), int(y * scale),
                0, 0,                      # ignored under SWP_NOSIZE, but must be ints
                SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW,
            )

        if not hasattr(_wf.BrowserView, "BrowserForm"):
            raise AttributeError("BrowserView.BrowserForm missing — pywebview layout changed")
        _wf.BrowserView.BrowserForm.move = _fixed_move
        _log("winforms BrowserForm.move patched OK")
    except Exception as e:
        _log(f"winforms move patch FAILED: {e}")


from data import TodoStore
from api import Api
from tray import TrayController
from hotkeys import (HotkeyManager, HOTKEY_TOGGLE_FLOAT, HOTKEY_TOGGLE_HIDE,
                     HOTKEY_QUICK_ADD, HOTKEY_TOGGLE_FOCUS)
import osapi as winapi   # cross-platform shim — backed by Windows or macOS


from paths import resource_root, user_root
RESOURCE_ROOT = resource_root()
USER_ROOT = user_root()
FRONTEND_PATH = RESOURCE_ROOT / "frontend" / "index.html"
QUICK_ADD_PATH = RESOURCE_ROOT / "frontend" / "quickadd.html"
DATA_FILE = USER_ROOT / "data" / "todos.json"
APP_ICON_PATH = RESOURCE_ROOT / "assets" / "checkera.ico"


def main():
    # 0. Repair pywebview's broken window-move before any window exists —
    # without this, dragging the frameless window raises on every mousemove.
    _patch_winforms_move()

    # 0b. Identify ourselves to Windows as "checkera" so the taskbar doesn't
    # group us under python.exe and use the Python icon. Must happen BEFORE
    # the first webview window is created.
    try:
        winapi.set_app_user_model_id("checkera")
    except Exception as e:
        print(f"[widget] AUMID set failed: {e}", file=sys.stderr)

    # 0c. Record whether the Google SDK actually imports in THIS build. The
    # packaged app has no console, so an import failure would otherwise surface
    # only as a misleading "SDK not installed" message in the UI.
    try:
        import gcal as _gcal
        if _gcal.is_library_available():
            _log("gcal SDK import OK")
        else:
            _log(f"gcal SDK IMPORT FAILED -> {getattr(_gcal, 'IMPORT_ERROR', 'unknown')}")
    except Exception as e:
        _log(f"gcal module itself failed to load: {type(e).__name__}: {e}")

    # 1. Backend
    store = TodoStore(DATA_FILE)
    deleted = store.clean_old_archived()
    if deleted:
        print(f"[housekeeping] auto-deleted {deleted} old archived task(s)")

    api = Api(store)

    # 2. Window
    saved = store.settings
    win_w = saved.get("window_w") or 320
    win_h = saved.get("window_h") or 440
    if not (200 <= win_w <= 800): win_w = 320
    if not (260 <= win_h <= 1000): win_h = 440

    # Detect primary screen size to validate saved position. Anything
    # off-screen (from a previous Tkinter version that used different defaults)
    # is discarded — we fall back to right-side default placement.
    try:
        import ctypes
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
    except Exception:
        screen_w, screen_h = 1920, 1080

    x = saved.get("window_x")
    y = saved.get("window_y")
    # Out-of-bounds → reset to right-side default
    if (x is None or y is None
        or not (0 <= x <= screen_w - 100)
        or not (0 <= y <= screen_h - 100)):
        x = screen_w - win_w - 24
        y = max(40, (screen_h - win_h) // 2 - 40)
        store.update_setting("window_x", None)
        store.update_setting("window_y", None)
    print(f"[widget] placing window at {x},{y} size {win_w}x{win_h}", flush=True)

    window = webview.create_window(
        title="Checkera",
        url=str(FRONTEND_PATH),
        js_api=api,
        width=win_w,
        height=win_h,
        x=x, y=y,
        min_size=(280, 320),
        resizable=True,
        on_top=True,
        frameless=True,            # no OS title bar — the header draws its own controls
        easy_drag=False,           # drag only via .pywebview-drag-region, so header
                                   # buttons and the task list stay clickable
        background_color="#1D1B18",
    )
    api.set_window(window)

    # Closing the X hides to tray rather than quitting
    def _on_closing():
        api.hide_to_tray()
        return False               # cancel the close
    try:
        window.events.closing += _on_closing
    except Exception:
        pass

    # 3. After webview is ready: tray, hotkeys, reminders, screen-capture exclusion
    def _on_loaded():
        # Taskbar hiding is deferred to a worker — see _settle_window_chrome for
        # why doing it here doesn't stick. The icon/capture calls below still run
        # now so the icon appears promptly; the worker re-applies them after.
        threading.Thread(target=_settle_window_chrome, args=(window,),
                         daemon=True).start()
        try:
            # Both calls go through the cross-platform shim. On Windows it
            # resolves hwnd via FindWindowW; on Mac it walks NSApp.windows()
            # and matches by title.
            if APP_ICON_PATH.exists():
                winapi.set_window_icon("Checkera", str(APP_ICON_PATH))
            winapi.exclude_from_capture("Checkera")
        except Exception as e:
            print(f"[win] capture exclusion / icon failed: {e}", file=sys.stderr)

        # Periodically persist window geometry
        def _save_geom():
            while True:
                try:
                    import time
                    time.sleep(5)
                    store.update_setting("window_w", window.width)
                    store.update_setting("window_h", window.height)
                    store.update_setting("window_x", window.x)
                    store.update_setting("window_y", window.y)
                except Exception:
                    pass
        threading.Thread(target=_save_geom, daemon=True).start()

    # 4. Tray
    def show():        api.show_window()
    def hide():        api.hide_to_tray()
    def add():         api.show_window(); window.evaluate_js("state.adding=true;render();")
    def quit_app():
        import os
        os._exit(0)

    tray = TrayController(on_show=show, on_hide=hide, on_add=add, on_quit=quit_app)
    tray.start()

    # 5. Hotkeys
    hotkeys = HotkeyManager(_ScheduleAdapter(window))
    hotkeys.register(HOTKEY_TOGGLE_FLOAT, lambda: api.show_window())
    hotkeys.register(HOTKEY_TOGGLE_HIDE,  lambda: api.hide_to_tray())
    hotkeys.register(HOTKEY_QUICK_ADD,    lambda: _open_quick_add(api, screen_w, screen_h))
    hotkeys.register(HOTKEY_TOGGLE_FOCUS, lambda: window.evaluate_js("quickToggleFocus()"))

    # 6. Reminders — fires Windows toasts based on the store's pending_reminders
    scheduler = _ReminderAdapter(store)
    scheduler.start()

    # 7. Start the webview event loop
    webview.start(_on_loaded, debug=False)

    # Cleanup
    hotkeys.unregister_all()
    scheduler.stop()
    tray.stop()


def _hide_taskbar_button(win) -> None:
    """Keep Checkera out of the taskbar (and Alt-Tab) so it lives only in the tray.

    A raw SetWindowLong(WS_EX_TOOLWINDOW) does NOT survive here: pywebview hosts
    the window in a WinForms Form, and WinForms recomputes CreateParams from its
    own ShowInTaskbar property every time it rebuilds the handle, restoring
    WS_EX_APPWINDOW and undoing the edit. Setting the property is the only thing
    that sticks. WinForms property access must happen on the UI thread, so this
    uses the same InvokeRequired/Invoke dance pywebview uses internally."""
    native = getattr(win, "native", None)
    if native is not None:
        def _apply():
            native.ShowInTaskbar = False

        try:
            if getattr(native, "InvokeRequired", False):
                from System import Func, Type
                native.Invoke(Func[Type](_apply))
            else:
                _apply()
        except Exception as e:
            print(f"[win] ShowInTaskbar failed: {e}", file=sys.stderr)

    # Belt and braces — the Win32 tool-window style also keeps it out of
    # Alt-Tab, and covers any non-WinForms backend.
    try:
        winapi.hide_from_taskbar("Checkera")
    except Exception as e:
        print(f"[win] hide_from_taskbar failed: {e}", file=sys.stderr)


def _settle_window_chrome(win) -> None:
    """Drop the taskbar button once WinForms has finished building the window.

    Doing this in the loaded callback does NOT work: WinForms is still showing
    and sizing the window at that point and rebuilds the native handle straight
    after, silently reverting the change (confirmed by probing the live window —
    the flag came back every time). Waiting until it settles makes it stick, and
    it's applied twice in case the first pass still lands too early.

    Flipping ShowInTaskbar itself forces a handle rebuild, which drops anything
    bound to the old HWND — so the icon and the screen-capture exclusion are
    re-applied AFTER, never before."""
    for delay in (2.0, 3.0):
        time.sleep(delay)
        _hide_taskbar_button(win)
        try:
            if APP_ICON_PATH.exists():
                winapi.set_window_icon("Checkera", str(APP_ICON_PATH))
            winapi.exclude_from_capture("Checkera")
        except Exception as e:
            print(f"[win] icon / capture re-apply failed: {e}", file=sys.stderr)


def _open_quick_add(api, screen_w: int, screen_h: int) -> None:
    """Pop the tiny quick-add window (Ctrl+Shift+N). Fired from a worker
    thread by the keyboard hotkey listener, so creating the window here
    is fine — pywebview supports create_window from non-main threads
    after webview.start() has been called."""
    # Already-open guard
    if api._quick_add_window is not None:
        try:
            api._quick_add_window.show()
            return
        except Exception:
            api._quick_add_window = None

    w_w, w_h = 380, 88
    x = max(0, (screen_w - w_w) // 2)
    y = max(0, screen_h // 3)
    # Use a distinct title from the main window ("Checkera") so the icon
    # lookup below can't accidentally target the main window via FindWindowW.
    qa_title = "Checkera · quick add"
    try:
        w = webview.create_window(
            title=qa_title,
            url=str(QUICK_ADD_PATH),
            js_api=api,
            width=w_w, height=w_h,
            x=x, y=y,
            frameless=True,
            on_top=True,
            easy_drag=True,
            resizable=False,
            background_color="#1D1B18",
        )
        api.set_quick_add_window(w)

        # Set the Checkera icon on the popup so Alt-Tab / taskbar don't show
        # Python's icon. The osapi shim resolves the right handle by title
        # on both Windows and macOS.
        def _qa_set_icon():
            try:
                if APP_ICON_PATH.exists():
                    winapi.set_window_icon(qa_title, str(APP_ICON_PATH))
            except Exception:
                pass
        try:
            w.events.loaded += _qa_set_icon
        except Exception:
            # Older pywebview: best-effort via a short delay
            threading.Timer(0.5, _qa_set_icon).start()
    except Exception as e:
        print(f"[widget] quick-add failed to open: {e}", file=sys.stderr)


def _get_hwnd(window):
    """Best-effort fetch of the underlying Win32 HWND for a pywebview window."""
    try:
        # pywebview exposes the native handle differently per platform/version
        gui = getattr(webview, "windows", None)
        # Most reliable: ask Win32 to find the window by title
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, window.title)
        return hwnd or None
    except Exception:
        return None


class _ScheduleAdapter:
    """Mimics enough of the Tk window API for HotkeyManager (only .after needed)."""
    def __init__(self, window):
        self.window = window

    def after(self, _ms, fn):
        # Run on a thread so we don't block the keyboard listener
        threading.Thread(target=fn, daemon=True).start()


class _ReminderAdapter:
    """Threaded reminder scheduler — replaces the Tk-based one for PyWebView."""
    CHECK_INTERVAL = 30   # seconds

    def __init__(self, store):
        from notifications import show_toast
        self.store = store
        self.show_toast = show_toast
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                # Reminder toasts (user-set, fires before due time)
                for t in self.store.pending_reminders():
                    self._fire_reminder(t)
                    self.store.mark_reminded(t.id)
                # Due-time toasts (fires at the exact due time if not done)
                for t in self.store.pending_due_notifications():
                    self._fire_due(t)
                    self.store.mark_due_notified(t.id)
            except Exception as e:
                print(f"[reminders] {e}", file=sys.stderr)
            self._stop.wait(self.CHECK_INTERVAL)

    def _fire_reminder(self, task):
        msg = self._task_summary(task, prefix=True)
        self.show_toast("Reminder", msg)

    def _fire_due(self, task):
        msg = self._task_summary(task, prefix=False)
        self.show_toast("Task is due", msg)

    @staticmethod
    def _task_summary(task, prefix: bool = False) -> str:
        from datetime import datetime
        s = task.name
        if task.due_date:
            try:
                d = datetime.strptime(task.due_date, "%Y-%m-%d").date()
                bit = f"due {d.strftime('%d %b')}"
                if task.due_time:
                    h, m = task.due_time.split(":")
                    hh = int(h)
                    ampm = "AM" if hh < 12 else "PM"
                    h12 = hh % 12 or 12
                    bit += f" · {h12}:{m} {ampm}"
                if prefix:
                    s += "  ·  " + bit
                else:
                    s += "  ·  " + bit
            except ValueError:
                pass
        return s


if __name__ == "__main__":
    main()
