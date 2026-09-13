"""Task storage and queries. JSON-backed, atomic writes."""
from __future__ import annotations

import json
import os
import threading
import uuid
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from styles import CATEGORIES, PRIORITIES

# Recognised recurrence strings (None / falsy → not recurring)
RECURRENCES = {"daily", "weekdays", "weekly", "monthly", "custom"}


def _shift_reminder(reminder_iso: Optional[str],
                    old_due_iso: str, new_due_iso: str,
                    old_due_time: Optional[str] = None,
                    new_due_time: Optional[str] = None) -> Optional[str]:
    """Move the reminder forward by the (date + optional time) delta the due
    moved. Preserves the user's chosen offset across the next recurring
    occurrence even if due_time was edited between cycles."""
    if not reminder_iso or not old_due_iso or not new_due_iso:
        return None
    try:
        rem_dt = datetime.fromisoformat(reminder_iso)
        old_d = datetime.strptime(old_due_iso, "%Y-%m-%d").date()
        new_d = datetime.strptime(new_due_iso, "%Y-%m-%d").date()
    except ValueError:
        return None
    delta = timedelta(days=(new_d - old_d).days)
    # If both occurrences have a due_time and they differ, fold that into
    # the shift so the reminder offset remains constant
    if old_due_time and new_due_time and old_due_time != new_due_time:
        try:
            old_t = datetime.strptime(old_due_time, "%H:%M")
            new_t = datetime.strptime(new_due_time, "%H:%M")
            delta += (new_t - old_t)
        except ValueError:
            pass
    shifted = rem_dt + delta
    return shifted.isoformat(timespec="minutes")


def next_due_date(due_iso: str, recurrence: str,
                  recurrence_days: Optional[list] = None,
                  anchor_day: Optional[int] = None) -> Optional[str]:
    """Advance an ISO date string by one recurrence step.

    Returns None if the inputs are invalid. For 'monthly' we use `anchor_day`
    (the series's original day-of-month) when provided — clipped to the target
    month's last day if shorter — so e.g. Jan 31 → Feb 28 → Mar 31 instead of
    Jan 31 → Feb 28 → Mar 28. For 'custom' we step forward day-by-day until
    landing on a weekday in `recurrence_days`."""
    if not due_iso or recurrence not in RECURRENCES:
        return None
    try:
        d = datetime.strptime(due_iso, "%Y-%m-%d").date()
    except ValueError:
        return None

    if recurrence == "daily":
        d = d + timedelta(days=1)
    elif recurrence == "weekdays":
        # Mon=0 ... Sun=6. Roll Sat/Sun forward to Monday.
        d = d + timedelta(days=1)
        while d.weekday() >= 5:
            d = d + timedelta(days=1)
    elif recurrence == "weekly":
        d = d + timedelta(days=7)
    elif recurrence == "monthly":
        # Same day next month, anchored to the series's original day if known,
        # otherwise the current d.day. Clamp to last valid day of target month.
        y, m = d.year, d.month + 1
        if m > 12:
            m = 1; y += 1
        from calendar import monthrange
        last = monthrange(y, m)[1]
        use_day = anchor_day if anchor_day is not None else d.day
        d = date(y, m, min(use_day, last))
    elif recurrence == "custom":
        # Step forward 1 day at a time until we hit a chosen weekday.
        # Bail out after 14 steps to avoid an infinite loop if days are empty.
        days = set(int(x) for x in (recurrence_days or []) if isinstance(x, int) or str(x).isdigit())
        if not days:
            return None
        for _ in range(14):
            d = d + timedelta(days=1)
            if d.weekday() in days:
                return d.strftime("%Y-%m-%d")
        return None

    return d.strftime("%Y-%m-%d")


@dataclass
class Task:
    id: str
    name: str
    category: str               # one of styles.CATEGORIES
    priority: Optional[str]     # one of styles.PRIORITIES or None
    due_date: Optional[str]     # "YYYY-MM-DD"
    due_time: Optional[str]     # "HH:MM" (24h)
    reminder_at: Optional[str]  # ISO datetime "YYYY-MM-DDTHH:MM"
    completed: bool
    created_at: str             # ISO datetime
    completed_at: Optional[str] # ISO datetime
    archived: bool
    gcal_event_id: Optional[str] = None    # phase 5
    reminded: bool = False                 # reminder-toast already fired
    due_notified: bool = False             # "task is due" toast already fired
    subtasks: list = field(default_factory=list)  # [{"id","text","done"}]
    recurrence: Optional[str] = None       # None | "daily" | "weekdays" | "weekly" | "monthly" | "custom"
    # For recurrence="custom" only: weekday ints (0=Mon..6=Sun) to fire on.
    recurrence_days: list = field(default_factory=list)
    # For recurrence="monthly": the user's original day-of-month (1..31).
    # Stamped on creation, propagated through every clone — so even after
    # auto-cleanup deletes the original task decades later, the anchor stays.
    recurrence_anchor: Optional[int] = None
    series_id: Optional[str] = None        # links all occurrences of a recurring task
    attendees: list = field(default_factory=list)  # ["alice@gmail.com", ...] — GCal event invitees
    focus_minutes_total: int = 0           # cumulative minutes spent in Focus Mode on this task

    def due_datetime(self) -> Optional[datetime]:
        """Combine due_date + due_time into a datetime. End-of-day if no time."""
        if not self.due_date:
            return None
        try:
            d = datetime.strptime(self.due_date, "%Y-%m-%d").date()
        except ValueError:
            return None
        if self.due_time:
            try:
                t = datetime.strptime(self.due_time, "%H:%M").time()
                return datetime.combine(d, t)
            except ValueError:
                pass
        return datetime.combine(d, datetime.max.time().replace(microsecond=0))

    def reminder_datetime(self) -> Optional[datetime]:
        if not self.reminder_at:
            return None
        try:
            return datetime.fromisoformat(self.reminder_at)
        except ValueError:
            return None

    def is_overdue(self, now: Optional[datetime] = None) -> bool:
        if self.completed or self.archived:
            return False
        dt = self.due_datetime()
        if not dt:
            return False
        return dt < (now or datetime.now())


DEFAULT_SETTINGS = {
    "user_name": "Rashi",
    "auto_clean_archive_days": 30,
    "last_news_fetch": None,
    "last_gcal_fetch": None,
    # Window geometry — auto-populated when user drags/resizes
    "window_x": None,
    "window_y": None,
    "window_w": None,
    "window_h": None,
    # Free-form notes scratchpad (single text blob — autosaved from frontend)
    "notes": "",
}


class TodoStore:
    """JSON-backed task store. All mutations save atomically."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Re-entrant lock: many TodoStore methods take it (any write path),
        # but `_save` is called from inside those — RLock lets the same
        # thread reenter without deadlocking. Cheap, prevents the 5-second
        # geometry-save thread from racing the JS-API thread.
        self._lock = threading.RLock()
        self._data = self._load()
        self._migrate_series_ids()

    def _migrate_series_ids(self) -> None:
        """Backfill series_id AND recurrence_anchor on legacy recurring tasks.
        Tasks with the same (name, category, recurrence) tuple share a series.
        For monthly series, the anchor day is taken from the earliest member's
        due_date and stamped on every member so it survives even when older
        siblings get auto-cleaned."""
        changed = False
        seen: dict[tuple, str] = {}
        # First pass — adopt any existing series_ids so we don't overwrite them
        for raw in self._data["tasks"]:
            if not raw.get("recurrence"):
                continue
            key = (raw["name"], raw["category"], raw["recurrence"])
            if raw.get("series_id"):
                seen.setdefault(key, raw["series_id"])
        # Second pass — assign series_id where missing
        for raw in self._data["tasks"]:
            if not raw.get("recurrence") or raw.get("series_id"):
                continue
            key = (raw["name"], raw["category"], raw["recurrence"])
            sid = seen.get(key)
            if sid is None:
                sid = str(uuid.uuid4())
                seen[key] = sid
            raw["series_id"] = sid
            changed = True
        # Third pass — backfill recurrence_anchor on monthly series
        groups: dict[str, list[dict]] = {}
        for raw in self._data["tasks"]:
            if raw.get("recurrence") == "monthly" and raw.get("series_id"):
                groups.setdefault(raw["series_id"], []).append(raw)
        for sid, members in groups.items():
            if any(m.get("recurrence_anchor") for m in members):
                # Already stamped — copy to any missing siblings
                anchor = next((m["recurrence_anchor"] for m in members
                               if m.get("recurrence_anchor")), None)
            else:
                # No anchor anywhere — derive from earliest's due_date
                with_due = [m for m in members if m.get("due_date")]
                if not with_due:
                    continue
                earliest = min(with_due, key=lambda m: m["due_date"])
                try:
                    anchor = datetime.strptime(earliest["due_date"], "%Y-%m-%d").day
                except ValueError:
                    anchor = None
            if anchor:
                for m in members:
                    if m.get("recurrence_anchor") != anchor:
                        m["recurrence_anchor"] = anchor
                        changed = True
        if changed:
            self._save()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"tasks": [], "settings": dict(DEFAULT_SETTINGS)}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("tasks", [])
            settings = dict(DEFAULT_SETTINGS)
            settings.update(data.get("settings", {}))
            data["settings"] = settings
            return data
        except (json.JSONDecodeError, OSError):
            # Corrupt file — back it up and start fresh rather than losing the user's data silently
            backup = self.path.with_suffix(".json.corrupt")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            return {"tasks": [], "settings": dict(DEFAULT_SETTINGS)}

    def _save(self) -> None:
        # Atomic: write to temp file in the same dir, then replace.
        # The lock around the json.dump prevents another thread mutating
        # self._data while we iterate it (would raise RuntimeError).
        with self._lock:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".todos-", suffix=".tmp", delete=False
            )
            try:
                # Snapshot under the lock so any concurrent mutation can't
                # corrupt the iteration. json.dump materialises immediately.
                json.dump(self._data, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp.name, self.path)
            except Exception:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                raise

    # ---------- CRUD ----------

    def add_task(self, name: str, category: str, priority: Optional[str] = None,
                 due_date: Optional[str] = None, due_time: Optional[str] = None,
                 reminder_at: Optional[str] = None,
                 recurrence: Optional[str] = None,
                 recurrence_days: Optional[list] = None,
                 attendees: Optional[list] = None) -> Task:
        if category not in CATEGORIES:
            raise ValueError(f"Invalid category: {category!r}")
        if priority is not None and priority not in PRIORITIES:
            raise ValueError(f"Invalid priority: {priority!r}")
        if recurrence is not None and recurrence not in RECURRENCES:
            raise ValueError(f"Invalid recurrence: {recurrence!r}")
        # Normalise recurrence_days: only meaningful for "custom"
        rdays = []
        if recurrence == "custom" and recurrence_days:
            rdays = sorted({int(x) for x in recurrence_days
                            if isinstance(x, int) or str(x).isdigit()
                            and 0 <= int(x) <= 6})
        # Clean & dedupe attendees (basic email shape, lowercase)
        clean_attendees = []
        seen = set()
        for raw in (attendees or []):
            e = (raw or "").strip().lower()
            if "@" in e and e not in seen:
                seen.add(e)
                clean_attendees.append(e)

        # For monthly recurrence, freeze the original day-of-month here so
        # it survives forever even if the original task is later auto-cleaned.
        anchor = None
        if recurrence == "monthly" and due_date:
            try:
                anchor = datetime.strptime(due_date, "%Y-%m-%d").day
            except ValueError:
                anchor = None

        task = Task(
            id=str(uuid.uuid4()),
            name=name.strip(),
            category=category,
            priority=priority,
            due_date=due_date,
            due_time=due_time,
            reminder_at=reminder_at,
            completed=False,
            created_at=datetime.now().replace(microsecond=0).isoformat(),
            completed_at=None,
            archived=False,
            recurrence=recurrence,
            recurrence_days=rdays,
            recurrence_anchor=anchor,
            series_id=(str(uuid.uuid4()) if recurrence else None),
            attendees=clean_attendees,
        )
        self._data["tasks"].append(asdict(task))
        self._save()
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        for raw in self._data["tasks"]:
            if raw["id"] == task_id:
                return Task(**raw)
        return None

    def _find_raw(self, task_id: str) -> Optional[dict]:
        for raw in self._data["tasks"]:
            if raw["id"] == task_id:
                return raw
        return None

    def edit_task(self, task_id: str, **fields) -> Optional[Task]:
        raw = self._find_raw(task_id)
        if not raw:
            return None
        allowed = {"name", "category", "priority", "due_date", "due_time",
                   "reminder_at", "gcal_event_id", "recurrence", "recurrence_days",
                   "recurrence_anchor", "series_id", "attendees"}
        # If user changes the reminder time, reset reminded flag so the new one fires
        if "reminder_at" in fields and fields["reminder_at"] != raw.get("reminder_at"):
            raw["reminded"] = False
        # Same for due_date / due_time changes
        if (("due_date" in fields and fields["due_date"] != raw.get("due_date")) or
            ("due_time" in fields and fields["due_time"] != raw.get("due_time"))):
            raw["due_notified"] = False
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"Cannot edit field: {k}")
            if k == "category" and v not in CATEGORIES:
                raise ValueError(f"Invalid category: {v!r}")
            if k == "priority" and v is not None and v not in PRIORITIES:
                raise ValueError(f"Invalid priority: {v!r}")
            if k == "recurrence" and v is not None and v not in RECURRENCES:
                raise ValueError(f"Invalid recurrence: {v!r}")
            if k == "recurrence_days":
                # Sanitise & coerce to sorted unique int list
                v = sorted({int(x) for x in (v or [])
                            if isinstance(x, int) or (isinstance(x, str) and x.isdigit())
                            and 0 <= int(x) <= 6})
                fields[k] = v
            if k == "attendees":
                cleaned = []
                seen = set()
                for raw_e in (v or []):
                    e = (raw_e or "").strip().lower()
                    if "@" in e and e not in seen:
                        seen.add(e)
                        cleaned.append(e)
                v = cleaned
                fields[k] = cleaned
            if k == "name":
                v = v.strip()
            raw[k] = v
        # Series-id management based on recurrence changes (after the loop):
        #   - Newly added recurrence on a task with no series_id → mint one
        #   - Recurrence cleared on an active task → end the series so future
        #     sweeps don't respawn it (propagate to completed siblings too)
        if "recurrence" in fields:
            new_rec = fields["recurrence"]
            old_rec_before = raw.get("recurrence") if "recurrence" not in fields else None
            # raw["recurrence"] is now the new value (set in the loop above)
            if new_rec and not raw.get("series_id"):
                raw["series_id"] = str(uuid.uuid4())
            # If recurrence is being set to monthly and we don't have an anchor
            # yet, freeze it from the current due_date right now — must persist
            # for the lifetime of the series.
            if new_rec == "monthly" and not raw.get("recurrence_anchor") and raw.get("due_date"):
                try:
                    raw["recurrence_anchor"] = datetime.strptime(raw["due_date"], "%Y-%m-%d").day
                except ValueError:
                    pass
            # Detect "recurrence cleared on this task" — if new_rec is None and
            # the patch contained a recurrence key (which means the user
            # explicitly removed it), end the series everywhere (recurrence
            # → None AND series_id cleared so legacy migration can't readopt).
            if not new_rec and raw.get("series_id"):
                sid = raw["series_id"]
                for other in self._data["tasks"]:
                    if other.get("series_id") == sid and other["id"] != task_id:
                        other["recurrence"] = None
                        other["series_id"] = None
                raw["series_id"] = None
        self._save()
        return Task(**raw)

    def toggle_complete(self, task_id: str) -> Optional[Task]:
        """Toggle completion. Completed tasks auto-archive. Recurring tasks
        no longer spawn the next occurrence eagerly here — `sweep_recurring`
        does that lazily, only when the next date actually arrives."""
        raw = self._find_raw(task_id)
        if not raw:
            return None
        if raw["completed"]:
            raw["completed"] = False
            raw["completed_at"] = None
            raw["archived"] = False
        else:
            raw["completed"] = True
            raw["completed_at"] = datetime.now().replace(microsecond=0).isoformat()
            raw["archived"] = True
        self._save()
        return Task(**raw)

    def delete_task(self, task_id: str) -> bool:
        """Permanently delete. Returns True if removed.

        Deleting an active (non-archived) recurring occurrence also ends the
        series — sibling completed tasks lose their recurrence so the sweep
        doesn't respawn the series later."""
        raw = self._find_raw(task_id)
        if not raw:
            return False
        was_active_recurring = (not raw.get("archived")) and raw.get("recurrence")
        sid = raw.get("series_id")
        self._data["tasks"] = [t for t in self._data["tasks"] if t["id"] != task_id]
        if was_active_recurring and sid:
            for t in self._data["tasks"]:
                if t.get("series_id") == sid:
                    t["recurrence"] = None
                    t["series_id"] = None
        self._save()
        return True

    def unarchive_task(self, task_id: str) -> Optional[Task]:
        """Bring an archived task back to active (un-completes it too)."""
        raw = self._find_raw(task_id)
        if not raw:
            return None
        raw["archived"] = False
        raw["completed"] = False
        raw["completed_at"] = None
        self._save()
        return Task(**raw)

    # ---------- Subtasks ----------

    def add_subtask(self, task_id: str, text: str) -> Optional[dict]:
        raw = self._find_raw(task_id)
        if not raw:
            return None
        sub = {"id": str(uuid.uuid4()), "text": text.strip(), "done": False}
        raw.setdefault("subtasks", []).append(sub)
        self._save()
        return sub

    def toggle_subtask(self, task_id: str, sub_id: str) -> Optional[dict]:
        raw = self._find_raw(task_id)
        if not raw:
            return None
        for s in raw.get("subtasks", []):
            if s["id"] == sub_id:
                s["done"] = not s.get("done", False)
                self._save()
                return s
        return None

    def edit_subtask(self, task_id: str, sub_id: str, text: str) -> Optional[dict]:
        raw = self._find_raw(task_id)
        if not raw:
            return None
        for s in raw.get("subtasks", []):
            if s["id"] == sub_id:
                s["text"] = text.strip()
                self._save()
                return s
        return None

    def delete_subtask(self, task_id: str, sub_id: str) -> bool:
        raw = self._find_raw(task_id)
        if not raw or "subtasks" not in raw:
            return False
        before = len(raw["subtasks"])
        raw["subtasks"] = [s for s in raw["subtasks"] if s["id"] != sub_id]
        if len(raw["subtasks"]) != before:
            self._save()
            return True
        return False

    # ---------- Focus Mode ----------

    def add_focus_minutes(self, task_id: str, minutes: int) -> Optional[Task]:
        raw = self._find_raw(task_id)
        if not raw:
            return None
        raw["focus_minutes_total"] = raw.get("focus_minutes_total", 0) + max(0, int(minutes))
        self._save()
        return Task(**raw)

    # ---------- Queries ----------

    def all_tasks(self) -> list[Task]:
        return [Task(**raw) for raw in self._data["tasks"]]

    def active_tasks(self) -> list[Task]:
        return [t for t in self.all_tasks() if not t.archived]

    def archived_tasks(self) -> list[Task]:
        return [t for t in self.all_tasks() if t.archived]

    def overdue_tasks(self, now: Optional[datetime] = None) -> list[Task]:
        return [t for t in self.active_tasks() if t.is_overdue(now)]

    def pending_reminders(self, now: Optional[datetime] = None) -> list[Task]:
        """Tasks with reminder_at in the past that haven't fired yet (not completed)."""
        now = now or datetime.now()
        out = []
        for t in self.active_tasks():
            if t.reminded or t.completed:
                continue
            rd = t.reminder_datetime()
            if rd and rd <= now:
                out.append(t)
        return out

    def mark_reminded(self, task_id: str) -> None:
        raw = self._find_raw(task_id)
        if raw and not raw.get("reminded"):
            raw["reminded"] = True
            self._save()

    def pending_due_notifications(self, now: Optional[datetime] = None) -> list[Task]:
        """Tasks whose due-time has passed, that aren't done, and haven't
        been notified yet. Used to fire 'task is due' toasts."""
        now = now or datetime.now()
        out = []
        for t in self.active_tasks():
            if t.completed or t.due_notified:
                continue
            dt = t.due_datetime()
            if dt and dt <= now:
                out.append(t)
        return out

    def mark_due_notified(self, task_id: str) -> None:
        raw = self._find_raw(task_id)
        if raw and not raw.get("due_notified"):
            raw["due_notified"] = True
            self._save()

    # ---------- Sorting / grouping ----------

    @staticmethod
    def sort_by_due(tasks: list[Task]) -> list[Task]:
        """Soonest first. Tasks without due date go last."""
        far_future = datetime.max
        return sorted(tasks, key=lambda t: t.due_datetime() or far_future)

    @staticmethod
    def sort_by_priority(tasks: list[Task]) -> list[Task]:
        """High first. No priority goes last."""
        order = {"high": 0, "medium": 1, "low": 2, None: 3}
        return sorted(tasks, key=lambda t: order.get(t.priority, 3))

    @staticmethod
    def group_by_category(tasks: list[Task]) -> dict[str, list[Task]]:
        groups: dict[str, list[Task]] = {c: [] for c in CATEGORIES}
        for t in tasks:
            groups.setdefault(t.category, []).append(t)
        return groups

    # Ordered keys for proximity grouping — preserved as render order
    PROXIMITY_GROUPS = ["Overdue", "Today", "Tomorrow", "This week", "Later", "Someday"]

    @classmethod
    def group_by_due_proximity(cls, tasks: list[Task]) -> dict[str, list[Task]]:
        """Bucket tasks by how soon they're due. Within each bucket, sort
        soonest first."""
        today = date.today()
        groups: dict[str, list[Task]] = {k: [] for k in cls.PROXIMITY_GROUPS}
        for t in tasks:
            if t.is_overdue():
                groups["Overdue"].append(t)
                continue
            if not t.due_date:
                groups["Someday"].append(t)
                continue
            try:
                d = datetime.strptime(t.due_date, "%Y-%m-%d").date()
            except ValueError:
                groups["Someday"].append(t)
                continue
            delta = (d - today).days
            if delta == 0:
                groups["Today"].append(t)
            elif delta == 1:
                groups["Tomorrow"].append(t)
            elif delta <= 7:
                groups["This week"].append(t)
            else:
                groups["Later"].append(t)
        far = datetime.max
        for k, items in groups.items():
            items.sort(key=lambda t: t.due_datetime() or far)
        return groups

    # ---------- Recurring sweep ----------

    def sweep_recurring(self) -> int:
        """Lazily spawn the next occurrence for each recurring series whose
        current open occurrence is done AND whose next due date has arrived.

        Returns the number of new occurrences spawned. Safe to call often —
        cheap iteration over in-memory tasks."""
        today_iso = date.today().isoformat()
        # Group tasks by series_id (only recurring series; everything else ignored)
        groups: dict[str, list[dict]] = {}
        for raw in self._data["tasks"]:
            sid = raw.get("series_id")
            if not sid:
                continue
            groups.setdefault(sid, []).append(raw)

        spawned = 0
        for sid, members in groups.items():
            # If any member is currently active (not archived), the series
            # already has an open occurrence — nothing to do.
            if any(not m.get("archived") for m in members):
                continue
            # Find the latest completed occurrence that still has recurrence on
            # it. If the user ended the series, recurrence will be None on all
            # members and we skip the spawn.
            recurring_members = [m for m in members
                                 if m.get("recurrence") and m.get("due_date")]
            if not recurring_members:
                continue
            latest = max(recurring_members, key=lambda m: m["due_date"])
            recurrence = latest["recurrence"]
            rdays = latest.get("recurrence_days") or []
            # Anchor day is stored on the task itself — survives auto-cleanup
            # of original siblings. Fall back to "earliest member's day" only
            # for legacy tasks that don't have it yet (migrated below).
            anchor_day = latest.get("recurrence_anchor")
            if recurrence == "monthly" and not anchor_day:
                earliest = min(recurring_members, key=lambda m: m["due_date"])
                try:
                    anchor_day = datetime.strptime(earliest["due_date"], "%Y-%m-%d").day
                except ValueError:
                    anchor_day = None

            # Advance step-by-step until we land on a date >= today
            nxt = next_due_date(latest["due_date"], recurrence, rdays, anchor_day)
            guard = 0
            while nxt and nxt < today_iso and guard < 400:
                step = next_due_date(nxt, recurrence, rdays, anchor_day)
                if not step or step == nxt:
                    break
                nxt = step
                guard += 1

            # Only spawn if the next-or-current date has actually arrived
            if not nxt or nxt > today_iso:
                continue

            clone = {
                "id": str(uuid.uuid4()),
                "name": latest["name"],
                "category": latest["category"],
                "priority": latest.get("priority"),
                "due_date": nxt,
                "due_time": latest.get("due_time"),
                "reminder_at": _shift_reminder(latest.get("reminder_at"),
                                               latest["due_date"], nxt),
                "completed": False,
                "created_at": datetime.now().replace(microsecond=0).isoformat(),
                "completed_at": None,
                "archived": False,
                "gcal_event_id": latest.get("gcal_event_id"),
                "reminded": False,
                "due_notified": False,
                "subtasks": [{"id": str(uuid.uuid4()), "text": s.get("text", ""), "done": False}
                             for s in latest.get("subtasks", [])],
                "recurrence": recurrence,
                "recurrence_days": list(rdays),
                "recurrence_anchor": anchor_day if recurrence == "monthly" else None,
                "series_id": sid,
                "attendees": list(latest.get("attendees", []) or []),
            }
            self._data["tasks"].append(clone)
            spawned += 1

        if spawned:
            self._save()
        return spawned

    def upcoming_recurrences(self) -> list[dict]:
        """For each recurring series whose current state is 'all completed',
        compute what the NEXT occurrence will look like (without spawning it).
        Used by the frontend to render muted preview rows so users know the
        series is alive even when no active task exists today.

        Returns: list of {name, category, recurrence, recurrence_days, next_date}
        sorted by next_date ascending."""
        today_iso = date.today().isoformat()
        groups: dict[str, list[dict]] = {}
        for raw in self._data["tasks"]:
            sid = raw.get("series_id")
            if not sid:
                continue
            groups.setdefault(sid, []).append(raw)

        out: list[dict] = []
        for sid, members in groups.items():
            # Skip series with an open occurrence — it's already in the active list
            if any(not m.get("archived") for m in members):
                continue
            recurring_members = [m for m in members
                                 if m.get("recurrence") and m.get("due_date")]
            if not recurring_members:
                continue
            latest = max(recurring_members, key=lambda m: m["due_date"])
            recurrence = latest["recurrence"]
            rdays = latest.get("recurrence_days") or []
            anchor_day = latest.get("recurrence_anchor")
            if recurrence == "monthly" and not anchor_day:
                earliest = min(recurring_members, key=lambda m: m["due_date"])
                try:
                    anchor_day = datetime.strptime(earliest["due_date"], "%Y-%m-%d").day
                except ValueError:
                    anchor_day = None
            nxt = next_due_date(latest["due_date"], recurrence, rdays, anchor_day)
            guard = 0
            while nxt and nxt < today_iso and guard < 400:
                step = next_due_date(nxt, recurrence, rdays, anchor_day)
                if not step or step == nxt:
                    break
                nxt = step
                guard += 1
            # Only surface previews that are STRICTLY in the future. Anything
            # at-or-before today would have been spawned by sweep_recurring.
            if not nxt or nxt <= today_iso:
                continue
            out.append({
                "name": latest["name"],
                "category": latest["category"],
                "recurrence": recurrence,
                "recurrence_days": rdays,
                "next_date": nxt,
                "due_time": latest.get("due_time"),
            })
        out.sort(key=lambda o: o["next_date"])
        return out

    # ---------- Stats ----------

    def stats(self, now: Optional[datetime] = None) -> dict:
        """Counts of completed tasks for today / this week / total, plus the
        longest consecutive-day streak of days with at least one completion.

        Uses each task's `completed_at` timestamp (only completed tasks count).
        Returns a plain dict so the frontend can render it without further
        processing."""
        now = now or datetime.now()
        today = now.date()
        # Monday-anchored week
        week_start = today - timedelta(days=today.weekday())

        done_today = 0
        done_week = 0
        done_total = 0
        # Set of days that had any completion — used for streak math
        days_with_done: set = set()

        for raw in self._data["tasks"]:
            if not raw.get("completed") or not raw.get("completed_at"):
                continue
            try:
                ts = datetime.fromisoformat(raw["completed_at"])
            except ValueError:
                continue
            d = ts.date()
            done_total += 1
            days_with_done.add(d)
            if d == today:
                done_today += 1
            if d >= week_start:
                done_week += 1

        # Current streak: count back from today (or yesterday if nothing today)
        # so a clean "today" doesn't break a streak that's about to be earned.
        current_streak = 0
        anchor = today if today in days_with_done else (today - timedelta(days=1))
        while anchor in days_with_done:
            current_streak += 1
            anchor -= timedelta(days=1)

        # Longest historical streak — single pass over sorted days
        longest_streak = 0
        if days_with_done:
            run = 1
            prev = None
            for d in sorted(days_with_done):
                if prev and (d - prev).days == 1:
                    run += 1
                else:
                    run = 1
                longest_streak = max(longest_streak, run)
                prev = d

        return {
            "done_today": done_today,
            "done_week": done_week,
            "done_total": done_total,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        }

    # ---------- Archive cleanup ----------

    def clean_old_archived(self, days: Optional[int] = None) -> int:
        """Delete archived tasks older than `days`. Returns number deleted."""
        if days is None:
            days = self.settings.get("auto_clean_archive_days", 30)
        if not days or days <= 0:
            return 0
        cutoff = datetime.now() - timedelta(days=days)
        kept = []
        deleted = 0
        for raw in self._data["tasks"]:
            if raw.get("archived") and raw.get("completed_at"):
                try:
                    ts = datetime.fromisoformat(raw["completed_at"])
                except ValueError:
                    ts = None
                if ts and ts < cutoff:
                    deleted += 1
                    continue
            kept.append(raw)
        if deleted:
            self._data["tasks"] = kept
            self._save()
        return deleted

    # ---------- Settings ----------

    @property
    def settings(self) -> dict:
        return self._data["settings"]

    def update_setting(self, key: str, value) -> None:
        with self._lock:
            self._data["settings"][key] = value
            self._save()
