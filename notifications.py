"""Windows toast notifications + reminder scheduler.

Notifications use winotify (a thin wrapper around Windows 10/11 toast XML).
Windows automatically respects the user's Focus Assist / DND / muted-volume
state, so we don't need to detect mute ourselves.

The scheduler runs on the Tk main thread via `after()` — no extra threads."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Callable

from data import TodoStore, Task
import styles as S


# winotify is Windows-only; degrade gracefully on other platforms
try:
    from winotify import Notification, audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False


def _icon_path() -> Optional[str]:
    from paths import resource_root
    assets = resource_root() / "assets"
    # Prefer the Checkera mark; fall back to legacy names
    for candidate in ("checkera-icon-128.png", "checkera-icon-64.png", "icon.png"):
        p = assets / candidate
        if p.exists():
            return str(p)
    return None


def _show_mac_toast(title: str, message: str) -> bool:
    """Native macOS Notification Center toast via osascript. Respects the
    user's Do Not Disturb / Focus mode automatically."""
    import subprocess
    # Escape double quotes for AppleScript
    t = (title or "").replace('"', '\\"')
    m = (message or "").replace('"', '\\"')
    script = f'display notification "{m}" with title "{t}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       check=False, capture_output=True, timeout=5)
        return True
    except Exception as e:
        print(f"[notification mac] failed: {e}", file=sys.stderr)
        return False


def show_toast(title: str, message: str, on_click: Optional[Callable] = None) -> bool:
    """Show a desktop notification. Returns True if shown, False if not
    supported. Windows uses winotify; macOS uses osascript. Linux gets a
    stderr fallback."""
    if sys.platform == "darwin":
        return _show_mac_toast(title, message)
    if not HAS_WINOTIFY:
        # Silent fallback: print to stderr so it's visible if running via `python` (not pythonw)
        print(f"[notification] {title}: {message}", file=sys.stderr)
        return False
    try:
        toast = Notification(
            app_id=S.APP_ID,
            title=title,
            msg=message,
            icon=_icon_path() or "",
            duration="short",
        )
        # Default Windows notification sound — respects system mute / Focus Assist
        toast.set_audio(audio.Default, loop=False)
        toast.show()
        return True
    except Exception as e:
        print(f"[notification] failed: {e}", file=sys.stderr)
        return False


class ReminderScheduler:
    """Polls the store every CHECK_INTERVAL_MS and fires toasts for any
    reminder whose time has arrived. Marks each as 'reminded' so it doesn't fire twice."""

    CHECK_INTERVAL_MS = 30_000   # 30 seconds — finest granularity user picks is HH:MM

    def __init__(self, tk_root, store: TodoStore, on_show_widget: Optional[Callable] = None):
        self.tk = tk_root
        self.store = store
        self.on_show_widget = on_show_widget
        self._running = False

    def start(self):
        self._running = True
        # Kick off on next tick — give the UI a moment to draw
        self.tk.after(2000, self._tick)

    def stop(self):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        try:
            self._check_and_fire()
        except Exception as e:
            print(f"[reminders] error: {e}", file=sys.stderr)
        finally:
            self.tk.after(self.CHECK_INTERVAL_MS, self._tick)

    def _check_and_fire(self):
        pending = self.store.pending_reminders()
        for t in pending:
            self._fire_for(t)
            self.store.mark_reminded(t.id)

    def _fire_for(self, task: Task):
        title = "Reminder"
        # Build descriptive message
        msg = task.name
        if task.due_date:
            from datetime import datetime
            try:
                dd = datetime.strptime(task.due_date, "%Y-%m-%d").date()
                msg += f"  ·  due {dd.strftime('%d/%m/%Y')}"
                if task.due_time:
                    hh, mm = task.due_time.split(":")
                    h = int(hh); ampm = "AM" if h < 12 else "PM"
                    h12 = h % 12 or 12
                    msg += f" {h12}:{mm} {ampm}"
            except (ValueError, AttributeError):
                pass
        show_toast(title, msg)
