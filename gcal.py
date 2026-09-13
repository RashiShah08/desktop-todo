"""Google Calendar integration: read events from all user calendars, push
tasks-with-due-dates as events, keep them in sync.

ONE-TIME SETUP (see SETUP.md or the README the app prints on first launch):

  1. Go to  https://console.cloud.google.com
  2. Create a project (or pick an existing one)
  3. APIs & Services → Enable APIs → enable "Google Calendar API"
  4. APIs & Services → Credentials → Create Credentials → OAuth client ID
     → Application type: "Desktop app" → Create
  5. Download the credentials JSON, save it as `credentials.json` next to
     widget.py in this project folder
  6. Run widget.py — on first launch it opens a browser for consent.
     After you allow access, a token is saved to `token.json` and you're done.

Files this module touches:
  • credentials.json   — provided by you (OAuth client secrets)
  • token.json         — created by the OAuth flow, holds your access token

Nothing is uploaded to any third party except Google's own Calendar API."""
from __future__ import annotations

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GCAL = True
    IMPORT_ERROR = None
except ImportError as e:
    HAS_GCAL = False
    # Keep the reason: when frozen there's no console, so a bare False here
    # is indistinguishable from "not installed" and impossible to diagnose.
    IMPORT_ERROR = f"{type(e).__name__}: {e}"
    HttpError = Exception   # placeholder so type refs don't break


SCOPES = ["https://www.googleapis.com/auth/calendar"]
from paths import user_root
PROJECT_ROOT = user_root()
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
CACHE_FILE = PROJECT_ROOT / "cache" / "gcal.json"

# Tag we set on every event we create — hidden from the user (lives under
# extendedProperties.private, not visible in any UI) but readable via the
# Calendar API. Used by scripts/cleanup_gcal.py to find "our" events.
APP_MARKER_KEY = "source"
APP_MARKER_VALUE = "checkera"
# Legacy marker values from earlier names — cleanup script matches both
APP_MARKER_LEGACY = ("focus-widget",)


# ─────────────────────────────────────────────────────────────────────
# Status checks
# ─────────────────────────────────────────────────────────────────────

def is_library_available() -> bool:
    return HAS_GCAL


def has_credentials_file() -> bool:
    return CREDENTIALS_FILE.exists()


def has_token() -> bool:
    return TOKEN_FILE.exists()


def setup_status() -> dict:
    """Summary of what's set up. UI uses this to decide which banner to show."""
    return {
        "library_installed": HAS_GCAL,
        "credentials_present": has_credentials_file(),
        "token_present": has_token(),
        "ready": HAS_GCAL and has_credentials_file() and has_token(),
    }


# ─────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────

def _load_credentials() -> Optional["Credentials"]:
    """Load and refresh saved creds. Returns None if missing/invalid."""
    if not has_token():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except (ValueError, OSError) as e:
        print(f"[gcal] token load failed: {e}", file=sys.stderr)
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
        except Exception as e:
            print(f"[gcal] token refresh failed: {e}", file=sys.stderr)
            return None
    if not creds or not creds.valid:
        return None
    return creds


def _save_credentials(creds: "Credentials") -> None:
    TOKEN_FILE.write_text(creds.to_json())


def authenticate_interactive() -> bool:
    """Run the OAuth consent flow. Pops a browser window — blocks until done.
    Returns True if a valid token was obtained and saved."""
    if not HAS_GCAL:
        return False
    if not has_credentials_file():
        print(f"[gcal] credentials.json not found at {CREDENTIALS_FILE}", file=sys.stderr)
        return False
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        _save_credentials(creds)
        return True
    except Exception as e:
        print(f"[gcal] auth flow failed: {e}", file=sys.stderr)
        return False


def _service():
    creds = _load_credentials()
    if not creds:
        return None
    try:
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[gcal] failed to build service: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────────────────────────────
# Read events
# ─────────────────────────────────────────────────────────────────────

def _local_tz():
    """Local tz info. Falls back to Asia/Kolkata if zoneinfo is unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Kolkata")
    except Exception:
        from datetime import timezone, timedelta as td
        return timezone(td(hours=5, minutes=30))


def _to_rfc3339(dt: datetime) -> str:
    """RFC3339 with timezone. If naive, treat as local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt.isoformat()


def _normalize_event(raw: dict, calendar_name: str, calendar_color: Optional[str]) -> dict:
    """Convert Google's event payload to a flat dict the UI can consume."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    all_day = "date" in start
    if all_day:
        start_dt = start.get("date")   # "2026-05-15"
        end_dt = end.get("date")
    else:
        start_dt = start.get("dateTime")   # ISO with offset
        end_dt = end.get("dateTime")
    return {
        "id": raw.get("id"),
        "title": raw.get("summary", "(no title)"),
        "start": start_dt,
        "end": end_dt,
        "all_day": all_day,
        "calendar_name": calendar_name,
        "calendar_color": calendar_color,
        "html_link": raw.get("htmlLink"),
    }


def list_events(start_dt: datetime, end_dt: datetime) -> list[dict]:
    """All events across all the user's calendars within [start_dt, end_dt).
    Returns normalized events sorted by start time. Empty list on error."""
    svc = _service()
    if not svc:
        return []
    try:
        cals = svc.calendarList().list().execute().get("items", [])
    except HttpError as e:
        print(f"[gcal] calendarList failed: {e}", file=sys.stderr)
        return []

    events: list[dict] = []
    for cal in cals:
        cal_id = cal.get("id")
        cal_name = cal.get("summary", "")
        cal_color = cal.get("backgroundColor")
        if not cal_id:
            continue
        try:
            resp = svc.events().list(
                calendarId=cal_id,
                timeMin=_to_rfc3339(start_dt),
                timeMax=_to_rfc3339(end_dt),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            ).execute()
        except HttpError as e:
            print(f"[gcal] events for {cal_name} failed: {e}", file=sys.stderr)
            continue
        for raw in resp.get("items", []):
            events.append(_normalize_event(raw, cal_name, cal_color))

    # Sort by start
    def _sort_key(e):
        s = e["start"]
        return s if s else ""
    events.sort(key=_sort_key)
    return events


def events_today() -> list[dict]:
    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=1)
    return list_events(start, end)


def events_this_week() -> list[dict]:
    """From today through 7 days out."""
    today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=7)
    return list_events(start, end)


# ─────────────────────────────────────────────────────────────────────
# Write events (task → GCal)
# ─────────────────────────────────────────────────────────────────────

def _reminders_for(task) -> dict:
    """Build the GCal `reminders` block for a task.

    • Completed task → suppress all reminders (event becomes a passive log entry).
    • Active task with reminder_at → popup override at the computed offset.
    • Otherwise → defer to the calendar's default reminders.
    """
    # Done tasks shouldn't ping — they're a record of completion now
    if getattr(task, "completed", False):
        return {"useDefault": False, "overrides": []}

    # No reminder set → defer to user's GCal defaults
    if not task.reminder_at:
        return {"useDefault": True}

    try:
        rem_dt = datetime.fromisoformat(task.reminder_at)
    except (ValueError, TypeError):
        return {"useDefault": True}

    due_dt = task.due_datetime()
    if not due_dt:
        return {"useDefault": True}

    offset_min = int(round((due_dt - rem_dt).total_seconds() / 60))
    # GCal accepts 0..40320 (4 weeks). Outside that range, defaults.
    if offset_min < 0:
        return {"useDefault": True}
    if offset_min > 40320:
        offset_min = 40320

    return {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": offset_min}],
    }


def _summary_for(task) -> str:
    """Event title — kept clean (no decorative prefix) so invitation emails
    and recipient calendars don't look noisy. We mark our events via the
    hidden extendedProperties field instead (see _push_marker)."""
    if getattr(task, "completed", False):
        return f"{task.name} — done"
    return task.name


def _description_for(task) -> str:
    """GCal event description.

    Shape:
      • Solo task (no attendees): just the meta line + steps. No greeting.
      • Shared task (has attendees): friendly opener + meta + steps + close.
        If there's no meta and no steps, collapses to a single inline line
        so invitees don't see weird blank gaps.
    """
    has_attendees = bool(getattr(task, "attendees", []) or [])

    # Build the meta line (priority · recurrence) — omit empty pieces
    meta_bits = []
    if task.priority and task.priority != "none":
        meta_bits.append(f"Priority: {task.priority}")
    if task.recurrence:
        rec = task.recurrence
        days = getattr(task, "recurrence_days", []) or []
        if rec == "custom" and days:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            rec = ", ".join(day_names[i] for i in days if 0 <= i <= 6)
        meta_bits.append(f"Repeats: {rec}")

    # Build the subtask checklist
    subs = list(getattr(task, "subtasks", []) or [])
    steps_lines = []
    if subs:
        steps_lines.append("Steps:")
        for s in subs:
            mark = "✓" if s.get("done") else "○"
            steps_lines.append(f"  {mark} {s.get('text', '')}")

    # No attendees → pure functional description, no greeting/close
    if not has_attendees:
        out = []
        if meta_bits:
            out.append(" · ".join(meta_bits))
        if steps_lines:
            if out:
                out.append("")
            out.extend(steps_lines)
        return "\n".join(out)

    # With attendees: friendly wrapper around the meta/steps
    has_content = bool(meta_bits or steps_lines)
    if not has_content:
        # Case 3 tightened: no awkward blank lines when there's nothing
        # to show between the greeting and the close.
        return ("Hi! Sharing this task with you. "
                "Feel free to RSVP from Google Calendar. Thanks!")

    lines = ["Hi! Sharing this task with you — here's the gist:", ""]
    if meta_bits:
        lines.append("  " + " · ".join(meta_bits))
    if steps_lines:
        if meta_bits:
            lines.append("")
        lines.extend(steps_lines)
    lines.append("")
    lines.append("Feel free to RSVP from Google Calendar. Thanks!")
    return "\n".join(lines)


_BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

def _rrule_for(task) -> Optional[list[str]]:
    """RRULE for a recurring task, or None for one-shot tasks."""
    rec = getattr(task, "recurrence", None)
    if not rec:
        return None
    if rec == "daily":
        return ["RRULE:FREQ=DAILY"]
    if rec == "weekdays":
        return ["RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"]
    if rec == "weekly":
        return ["RRULE:FREQ=WEEKLY"]
    if rec == "monthly":
        return ["RRULE:FREQ=MONTHLY"]
    if rec == "custom":
        days = sorted(set(int(x) for x in (getattr(task, "recurrence_days", []) or [])
                          if 0 <= int(x) <= 6))
        if not days:
            return None
        byday = ",".join(_BYDAY[i] for i in days)
        return [f"RRULE:FREQ=WEEKLY;BYDAY={byday}"]
    return None


def push_task(task, calendar_id: str = "primary") -> Optional[str]:
    """Create a calendar event for a task with a due date.
    Returns the new event_id, or None on failure."""
    svc = _service()
    if not svc or not task.due_date:
        return None

    body = {
        "summary": _summary_for(task),
        "description": _description_for(task),
        "reminders": _reminders_for(task),
        "extendedProperties": {"private": {APP_MARKER_KEY: APP_MARKER_VALUE}},
    }
    rrule = _rrule_for(task)
    if rrule:
        body["recurrence"] = rrule
    attendees = list(getattr(task, "attendees", []) or [])
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    if task.due_time:
        # Timed event — 30 min default duration
        try:
            start = datetime.strptime(f"{task.due_date} {task.due_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        end = start + timedelta(minutes=30)
        body["start"] = {"dateTime": start.isoformat(), "timeZone": _local_tz_name()}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": _local_tz_name()}
    else:
        # All-day event
        body["start"] = {"date": task.due_date}
        end_d = (datetime.strptime(task.due_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        body["end"] = {"date": end_d}

    try:
        # sendUpdates="all" tells Google to email any attendees on the event
        # so they get the invitation. Without it, the attendees array would be
        # silent (no notification — they'd only see it if they manually checked
        # their calendar). For a "share a task" feature, we want the email.
        send_updates = "all" if body.get("attendees") else "none"
        created = svc.events().insert(
            calendarId=calendar_id, body=body, sendUpdates=send_updates,
        ).execute()
        return created.get("id")
    except HttpError as e:
        print(f"[gcal] push_task failed: {e}", file=sys.stderr)
        return None


def update_task_event(task, calendar_id: str = "primary") -> bool:
    """Update an existing GCal event to match the task."""
    if not task.gcal_event_id:
        return False
    svc = _service()
    if not svc or not task.due_date:
        return False
    body = {
        "summary": _summary_for(task),
        "description": _description_for(task),
        "reminders": _reminders_for(task),
        "extendedProperties": {"private": {APP_MARKER_KEY: APP_MARKER_VALUE}},
        # Always push the recurrence rule explicitly. Empty list clears any
        # existing RRULE on the GCal side — so if the user switches a task
        # from "daily" to "none", the event stops repeating. Without this,
        # patch's merge-patch semantics would leave the old rule in place.
        "recurrence": _rrule_for(task) or [],
    }
    attendees = list(getattr(task, "attendees", []) or [])
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    if task.due_time:
        try:
            start = datetime.strptime(f"{task.due_date} {task.due_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return False
        end = start + timedelta(minutes=30)
        body["start"] = {"dateTime": start.isoformat(), "timeZone": _local_tz_name()}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": _local_tz_name()}
    else:
        body["start"] = {"date": task.due_date}
        end_d = (datetime.strptime(task.due_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        body["end"] = {"date": end_d}
    try:
        # Same sendUpdates semantics as push_task — only notify if attendees
        send_updates = "all" if body.get("attendees") else "none"
        svc.events().patch(
            calendarId=calendar_id, eventId=task.gcal_event_id, body=body,
            sendUpdates=send_updates,
        ).execute()
        return True
    except HttpError as e:
        # 404 = event was deleted on GCal side. Caller may want to push as new.
        print(f"[gcal] update_task_event failed: {e}", file=sys.stderr)
        return False


def delete_task_event(task, calendar_id: str = "primary") -> bool:
    if not task.gcal_event_id:
        return False
    svc = _service()
    if not svc:
        return False
    try:
        svc.events().delete(calendarId=calendar_id, eventId=task.gcal_event_id).execute()
        return True
    except HttpError as e:
        # If already gone (404), treat as success
        if getattr(e, "resp", None) and e.resp.status == 404:
            return True
        print(f"[gcal] delete_task_event failed: {e}", file=sys.stderr)
        return False


def _local_tz_name() -> str:
    """IANA tz name passed to Google when creating events."""
    return "Asia/Kolkata"


# ─────────────────────────────────────────────────────────────────────
# Cache for offline display
# ─────────────────────────────────────────────────────────────────────

def save_cache(events: list[dict], window: str = "today") -> datetime:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().replace(microsecond=0)
    data = {"fetched_at": now.isoformat(), "window": window, "events": events}
    try:
        CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as e:
        print(f"[gcal] cache save failed: {e}", file=sys.stderr)
    return now


def load_cache() -> tuple[list[dict], Optional[datetime], Optional[str]]:
    if not CACHE_FILE.exists():
        return [], None, None
    try:
        data = json.loads(CACHE_FILE.read_text())
        ts = data.get("fetched_at")
        return data.get("events", []), (datetime.fromisoformat(ts) if ts else None), data.get("window")
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"[gcal] cache load failed: {e}", file=sys.stderr)
        return [], None, None
