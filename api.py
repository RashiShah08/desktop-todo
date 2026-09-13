"""JS↔Python bridge for the PyWebView frontend.

Exposed methods are callable from the frontend via:
    window.pywebview.api.<method_name>(...)

Keep this thin — push real logic into data.py / news.py / gcal.py."""
from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime, date as _date, timedelta as _td
from typing import Optional

from data import TodoStore, Task
import news as news_mod
import gcal


# Display labels for the three categories. Data key stays as-is for backward
# compat; only the UI label changes (Learning → College per latest design).
CATEGORY_LABEL = {"work": "Work", "personal": "Personal", "learning": "College"}
CATEGORY_FROM_LABEL = {v: k for k, v in CATEGORY_LABEL.items()}
# Tolerate the old label too in case anything sends "Learning"
CATEGORY_FROM_LABEL["Learning"] = "learning"


def _task_to_dict(t: Task) -> dict:
    """Shape a Task for the frontend (camelCase, split reminder date+time)."""
    rem_date = None
    rem_time = None
    if t.reminder_at:
        try:
            dt = datetime.fromisoformat(t.reminder_at)
            rem_date = dt.strftime("%Y-%m-%d")
            rem_time = dt.strftime("%H:%M")
        except ValueError:
            pass
    subs = list(getattr(t, "subtasks", []) or [])
    return {
        "id": t.id,
        "name": t.name,
        "category": CATEGORY_LABEL.get(t.category, "Work"),
        "priority": t.priority or "none",
        "dueDate": t.due_date,
        "dueTime": t.due_time,
        "reminderDate": rem_date,
        "reminderTime": rem_time,
        "completed": t.completed,
        "archived": t.archived,
        "gcalEventId": t.gcal_event_id,
        "subtasks": subs,
        "recurrence": getattr(t, "recurrence", None) or "none",
        "recurrenceDays": list(getattr(t, "recurrence_days", []) or []),
        "recurrenceAnchor": getattr(t, "recurrence_anchor", None),
        "attendees": list(getattr(t, "attendees", []) or []),
        "focusMinutesTotal": getattr(t, "focus_minutes_total", 0) or 0,
    }


def _headline_to_dict(h) -> dict:
    return {
        "id": id(h),
        "source": h.source,
        "headline": h.title,
        "url": h.url,
        "time": _time_ago(h.timestamp) if h.timestamp else "",
        "description": h.description or "",
    }


_VALID_RECURRENCE = ("daily", "weekdays", "weekly", "monthly", "custom")


def _first_recurrence_date(recurrence: str,
                           recurrence_days: Optional[list] = None) -> str:
    """First-occurrence date for a recurring task with no user-set due date.

    Today for most recurrence types; for "weekdays" we roll past Sat/Sun;
    for "custom" we roll forward to the next day matching `recurrence_days`."""
    d = _date.today()
    if recurrence == "weekdays":
        while d.weekday() >= 5:
            d = d + _td(days=1)
    elif recurrence == "custom":
        days = set(int(x) for x in (recurrence_days or [])
                   if (isinstance(x, int) or str(x).isdigit()) and 0 <= int(x) <= 6)
        if days:
            for _ in range(7):
                if d.weekday() in days:
                    break
                d = d + _td(days=1)
    return d.isoformat()


def _time_ago(ts: float) -> str:
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


class Api:
    """Methods callable from JS via window.pywebview.api.*"""

    def __init__(self, store: TodoStore):
        self.store = store
        self._window = None       # set by widget.py once the window exists
        self._quick_add_window = None  # second pywebview window for Ctrl+Shift+N

    def set_window(self, w):
        self._window = w

    def set_quick_add_window(self, w):
        self._quick_add_window = w

    # ─── State ──────────────────────────────────────────────
    def get_state(self) -> dict:
        # Lazily materialise any recurring occurrences whose date has arrived
        try:
            self.store.sweep_recurring()
        except Exception as e:
            print(f"[api] sweep_recurring error: {e}", file=sys.stderr)
        active = self.store.active_tasks()
        archived = self.store.archived_tasks()
        try:
            upcoming = self.store.upcoming_recurrences()
        except Exception as e:
            print(f"[api] upcoming error: {e}", file=sys.stderr)
            upcoming = []
        return {
            "tasks": [_task_to_dict(t) for t in active],
            "doneItems": [_task_to_dict(t) for t in archived],
            "upcoming": upcoming,
            "gcalConnected": bool(gcal.is_library_available()
                                  and gcal.setup_status()["ready"]),
        }

    # ─── Tasks ─────────────────────────────────────────────
    def add_task(self, name: str, category: str = "Work",
                 priority: Optional[str] = None,
                 due_date: Optional[str] = None,
                 due_time: Optional[str] = None,
                 reminder_at: Optional[str] = None,
                 recurrence: Optional[str] = None,
                 recurrence_days: Optional[list] = None,
                 attendees: Optional[list] = None) -> dict:
        cat = CATEGORY_FROM_LABEL.get(category, "work")
        prio = None if (not priority or priority == "none") else priority
        rec = recurrence if recurrence in _VALID_RECURRENCE else None
        rdays = recurrence_days if rec == "custom" else None
        # If "custom" was picked with no days, treat it as no recurrence
        # rather than silently creating a non-firing series.
        if rec == "custom" and not rdays:
            rec = None
            rdays = None
        # Recurring tasks need a start date — anchor to today if user didn't pick one.
        if rec and not due_date:
            due_date = _first_recurrence_date(rec, rdays)
        try:
            t = self.store.add_task(name, cat, priority=prio,
                                    due_date=due_date, due_time=due_time,
                                    reminder_at=reminder_at, recurrence=rec,
                                    recurrence_days=rdays, attendees=attendees)
            self._sync_push(t)
            return {"ok": True, "task": _task_to_dict(t)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def toggle_task(self, task_id: str) -> dict:
        t = self.store.toggle_complete(task_id)
        if t is None:
            return {"ok": False}
        # For recurring tasks the GCal side is a single RRULE series — we
        # don't want completing one occurrence to flip the series title.
        # Local completion is enough.
        if t.gcal_event_id and not t.recurrence:
            self._sync_update(t)
        return {"ok": True, "task": _task_to_dict(t)}

    def delete_task(self, task_id: str) -> dict:
        # Capture the task before deletion so we can remove its GCal event
        t = self.store.get_task(task_id)
        ok = self.store.delete_task(task_id)
        if ok and t:
            self._sync_delete(t)
        return {"ok": ok}

    def edit_task(self, task_id: str, fields: Optional[dict] = None) -> dict:
        fields = dict(fields or {})
        if "category" in fields:
            fields["category"] = CATEGORY_FROM_LABEL.get(fields["category"], fields["category"])
        if fields.get("priority") in (None, "none"):
            fields["priority"] = None
        # Whitelist defends against arbitrary keys from the JS side
        allowed = {"name", "category", "priority", "due_date", "due_time",
                   "reminder_at", "gcal_event_id", "recurrence", "recurrence_days",
                   "attendees"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        # Normalise recurrence: "none" / "" → None
        if "recurrence" in fields and fields["recurrence"] in ("none", "", None):
            fields["recurrence"] = None
        # If recurrence isn't "custom", recurrence_days is meaningless — clear it
        if fields.get("recurrence") != "custom" and "recurrence_days" in fields:
            fields["recurrence_days"] = []
        # If a recurrence is being applied and no due_date exists (neither
        # in this patch nor on the existing task), anchor to today.
        if fields.get("recurrence"):
            existing = self.store.get_task(task_id)
            current_due = (fields.get("due_date") if "due_date" in fields
                           else (existing.due_date if existing else None))
            if not current_due:
                fields["due_date"] = _first_recurrence_date(
                    fields["recurrence"], fields.get("recurrence_days"))
        try:
            t = self.store.edit_task(task_id, **fields)
            if t:
                self._sync_update(t)
            return {"ok": True, "task": _task_to_dict(t) if t else None}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def restore_task(self, task_id: str) -> dict:
        t = self.store.unarchive_task(task_id)
        return {"ok": t is not None}

    # ─── Subtasks ──────────────────────────────────────────
    def add_subtask(self, task_id: str, text: str) -> dict:
        if not text or not text.strip():
            return {"ok": False, "error": "empty"}
        sub = self.store.add_subtask(task_id, text)
        self._sync_subtask_change(task_id)
        return {"ok": bool(sub), "subtask": sub}

    def toggle_subtask(self, task_id: str, sub_id: str) -> dict:
        sub = self.store.toggle_subtask(task_id, sub_id)
        self._sync_subtask_change(task_id)
        return {"ok": bool(sub), "subtask": sub}

    def edit_subtask(self, task_id: str, sub_id: str, text: str) -> dict:
        if not text or not text.strip():
            return {"ok": False, "error": "empty"}
        sub = self.store.edit_subtask(task_id, sub_id, text)
        self._sync_subtask_change(task_id)
        return {"ok": bool(sub), "subtask": sub}

    def delete_subtask(self, task_id: str, sub_id: str) -> dict:
        ok = self.store.delete_subtask(task_id, sub_id)
        self._sync_subtask_change(task_id)
        return {"ok": ok}

    def _sync_subtask_change(self, task_id: str) -> None:
        """After any subtask mutation, push the new description to GCal so
        the calendar event reflects the updated checklist."""
        t = self.store.get_task(task_id)
        if t and t.gcal_event_id and not t.recurrence:
            self._sync_update(t)

    # ─── GCal sync helpers (fire-and-forget on a worker thread) ──────
    @staticmethod
    def _gcal_ready() -> bool:
        return gcal.is_library_available() and gcal.setup_status().get("ready")

    def _sync_push(self, task: Task) -> None:
        """Push a brand-new task as a GCal event (only if it has a due date)."""
        if not self._gcal_ready() or not task.due_date:
            return
        store = self.store
        def worker():
            try:
                event_id = gcal.push_task(task)
            except Exception as e:
                print(f"[gcal] push error: {e}", file=sys.stderr)
                return
            if event_id:
                try:
                    store.edit_task(task.id, gcal_event_id=event_id)
                except (ValueError, RuntimeError):
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def _sync_update(self, task: Task) -> None:
        """Update an existing GCal event, or push a new one if the task didn't
        have an event yet (e.g. due date was added during edit)."""
        if not self._gcal_ready():
            return
        store = self.store
        def worker():
            try:
                if task.gcal_event_id:
                    ok = gcal.update_task_event(task)
                    if ok:
                        return
                    # Event vanished on GCal side — recreate
                if task.due_date:
                    try:
                        new_id = gcal.push_task(task)
                    except Exception as e:
                        print(f"[gcal] re-push error: {e}", file=sys.stderr)
                        return
                    if new_id:
                        try:
                            store.edit_task(task.id, gcal_event_id=new_id)
                        except (ValueError, RuntimeError):
                            pass
            except Exception as e:
                print(f"[gcal] update error: {e}", file=sys.stderr)
        threading.Thread(target=worker, daemon=True).start()

    def _sync_delete(self, task: Task) -> None:
        """Remove the GCal event for a deleted task."""
        if not self._gcal_ready() or not task.gcal_event_id:
            return
        def worker():
            try:
                gcal.delete_task_event(task)
            except Exception as e:
                print(f"[gcal] delete error: {e}", file=sys.stderr)
        threading.Thread(target=worker, daemon=True).start()

    # ─── News ──────────────────────────────────────────────
    def get_news(self, force: bool = False) -> list[dict]:
        try:
            headlines, _ts, _was_fresh = news_mod.get_news(force_refresh=force)
            return [_headline_to_dict(h) for h in headlines]
        except Exception as e:
            print(f"[api] get_news failed: {e}", file=sys.stderr)
            return []

    # ─── GCal ──────────────────────────────────────────────
    def gcal_status(self) -> dict:
        return gcal.setup_status() if gcal.is_library_available() else {
            "library_installed": False, "ready": False,
            "credentials_present": False, "token_present": False,
        }

    def open_gcal_setup(self) -> dict:
        # Open the Google Cloud console in the user's browser so they
        # can fetch credentials.json. Setup instructions printed to console.
        webbrowser.open_new_tab("https://console.cloud.google.com/apis/credentials")
        return {
            "ok": True,
            "instructions": (
                "1. Create a project + enable Google Calendar API\n"
                "2. Create OAuth client ID for Desktop app\n"
                "3. Download credentials.json into the project folder\n"
                "4. Restart the widget"
            ),
        }

    def authorize_gcal(self) -> dict:
        ok = gcal.authenticate_interactive() if gcal.is_library_available() else False
        return {"ok": ok}

    def connect_gcal(self) -> dict:
        """Smart entry point for the in-widget Connect button.

        Behavior:
          • library missing → asks user to `pip install` the SDKs
          • credentials.json missing → opens the Cloud Console setup page
          • everything in place → kicks off the OAuth flow in a background
            thread (returns immediately so the JS bridge doesn't block).
        The browser tab pops up via google_auth_oauthlib's run_local_server.
        Frontend can poll get_state() to detect when gcalConnected flips."""
        if not gcal.is_library_available():
            return {
                "ok": False,
                "stage": "library_missing",
                "message": ("Google Calendar SDK not installed. Run: "
                            "pip install google-auth-oauthlib google-api-python-client"),
            }
        status = gcal.setup_status()
        if not status.get("credentials_present"):
            webbrowser.open_new_tab("https://console.cloud.google.com/apis/credentials")
            return {
                "ok": False,
                "stage": "no_credentials",
                "message": ("credentials.json not found in the project folder. "
                            "Download it from the Cloud Console, rename it to "
                            "credentials.json, and place it next to widget.py."),
            }
        if status.get("ready"):
            return {"ok": True, "stage": "already_connected"}

        # Run the (blocking) OAuth flow on a worker thread so this JS-API
        # call returns immediately. The frontend polls get_state to refresh.
        import threading
        def _run():
            try:
                ok = gcal.authenticate_interactive()
                print(f"[gcal] auth flow result: {ok}", flush=True)
            except Exception as e:
                print(f"[gcal] auth flow exception: {e}", file=sys.stderr, flush=True)
        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "stage": "auth_started"}

    # ─── Window controls ──────────────────────────────────
    def minimize_window(self) -> None:
        if self._window:
            try: self._window.minimize()
            except Exception: pass

    def hide_to_tray(self) -> None:
        if self._window:
            try: self._window.hide()
            except Exception: pass

    def show_window(self) -> None:
        if self._window:
            try: self._window.show()
            except Exception: pass

    def open_url(self, url: str) -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    # ─── Auto-start on boot ─────────────────────────────────
    def get_autostart_status(self) -> dict:
        try:
            import startup
            if sys.platform == "darwin":
                return {"supported": True, **startup._mac_status()}
            if sys.platform == "win32":
                return {"supported": True, **startup.status()}
            return {"supported": False, "installed": False}
        except Exception as e:
            print(f"[api] get_autostart_status failed: {e}", file=sys.stderr)
            return {"supported": False, "installed": False}

    def set_autostart(self, enabled: bool) -> dict:
        try:
            import startup
            is_mac = sys.platform == "darwin"
            is_win = sys.platform == "win32"
            if not (is_mac or is_win):
                return {"ok": False, "error": "unsupported platform"}
            if enabled:
                path = startup._mac_install() if is_mac else startup.install()
                return {"ok": True, "installed": True, "path": str(path)}
            else:
                removed = startup._mac_uninstall() if is_mac else startup.uninstall()
                return {"ok": True, "installed": False, "removed": removed}
        except Exception as e:
            print(f"[api] set_autostart failed: {e}", file=sys.stderr)
            return {"ok": False, "error": str(e)}

    # ─── Settings ──────────────────────────────────────────
    def get_setting(self, key: str):
        return self.store.settings.get(key)

    def set_setting(self, key: str, value) -> None:
        self.store.update_setting(key, value)

    # ─── Quick-add popup (Ctrl+Shift+N) ────────────────────
    def quickadd_save(self, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "empty"}
        try:
            t = self.store.add_task(name, "work")
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._sync_push(t)
        self._destroy_quick_add()
        return {"ok": True}

    def quickadd_cancel(self) -> dict:
        self._destroy_quick_add()
        return {"ok": True}

    def _destroy_quick_add(self) -> None:
        w = self._quick_add_window
        self._quick_add_window = None
        if w is None:
            return
        try:
            w.destroy()
        except Exception:
            pass

    # ─── Focus Mode ─────────────────────────────────────────
    def focus_session_complete(self, task_id: str, minutes: int) -> dict:
        t = self.store.add_focus_minutes(task_id, minutes)
        if t:
            try:
                from notifications import show_toast
                show_toast("Focus session complete",
                           f"{int(minutes)} min on “{t.name}”")
            except Exception as e:
                print(f"[api] focus toast failed: {e}", file=sys.stderr)
        return {"ok": t is not None}

    # ─── Stats ─────────────────────────────────────────────
    def get_stats(self) -> dict:
        try:
            return self.store.stats()
        except Exception as e:
            print(f"[api] get_stats failed: {e}", file=sys.stderr)
            return {
                "done_today": 0, "done_week": 0, "done_total": 0,
                "current_streak": 0, "longest_streak": 0,
            }

    # ─── Notes ─────────────────────────────────────────────
    def get_notes(self) -> str:
        return self.store.settings.get("notes", "") or ""

    def set_notes(self, text: str) -> dict:
        try:
            self.store.update_setting("notes", text or "")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
