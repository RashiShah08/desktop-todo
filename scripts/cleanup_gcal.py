"""One-off cleanup: delete all calendar events that this widget created.

What it does:
  • Lists events in the user's primary calendar from 6 months ago to 1 year ahead
  • Identifies "ours" by either: description containing "Rashi's Desktop Todo"
    OR summary starting with ☑ / ✅ (recurring series get a single insertion)
  • Asks for confirmation, then deletes them one by one

Run from the project root:
    python scripts/cleanup_gcal.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the project root importable so we can reuse gcal.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gcal  # noqa: E402


def _is_widget_event(ev: dict) -> bool:
    """Identify events the widget created. We check three signals so this
    works on old data (pre-marker) and new data alike:
      1. extendedProperties.private.source == "checkera"        (preferred)
         — or any legacy value listed in gcal.APP_MARKER_LEGACY (e.g. "focus-widget")
      2. legacy description contains "Rashi's Desktop Todo"
      3. legacy title starts with ☑ or ✅
    """
    ext = (ev.get("extendedProperties") or {}).get("private") or {}
    marker = ext.get(gcal.APP_MARKER_KEY)
    if marker == gcal.APP_MARKER_VALUE or marker in gcal.APP_MARKER_LEGACY:
        return True
    desc = ev.get("description") or ""
    summary = ev.get("summary") or ""
    if "Rashi's Desktop Todo" in desc:
        return True
    if summary.startswith("☑ ") or summary.startswith("✅ "):
        return True
    return False


def main() -> int:
    if not gcal.is_library_available():
        print("Google API libs not installed. Run:")
        print("  pip install google-auth-oauthlib google-api-python-client")
        return 1
    status = gcal.setup_status()
    if not status["ready"]:
        print("GCal not connected. Open the widget and click Connect first.")
        print(f"  credentials.json present: {status['credentials_present']}")
        print(f"  token.json present:       {status['token_present']}")
        return 1

    svc = gcal._service()
    if not svc:
        print("Could not build the Calendar service.")
        return 1

    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=180)).isoformat()
    window_end = (now + timedelta(days=365)).isoformat()

    print(f"Scanning events from {window_start} to {window_end} …")
    page_token = None
    candidates: list[dict] = []
    while True:
        resp = svc.events().list(
            calendarId="primary",
            timeMin=window_start,
            timeMax=window_end,
            singleEvents=False,            # include recurring series, not expanded
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            if _is_widget_event(ev):
                candidates.append(ev)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if not candidates:
        print("No widget-created events found. Calendar is already clean.")
        return 0

    print()
    print(f"Found {len(candidates)} event(s) created by the widget:")
    for ev in candidates:
        summary = ev.get("summary", "(no title)")
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or "?"
        recurring = " (recurring)" if ev.get("recurrence") else ""
        print(f"  • {summary}{recurring}   start={start}")

    print()
    confirm = input(f"Delete all {len(candidates)} event(s)? Type 'yes' to confirm: ").strip().lower()
    if confirm != "yes":
        print("Aborted. Nothing deleted.")
        return 0

    deleted = 0
    failed = 0
    for ev in candidates:
        try:
            svc.events().delete(calendarId="primary", eventId=ev["id"]).execute()
            deleted += 1
            print(f"  ✓ deleted: {ev.get('summary')}")
        except Exception as e:
            failed += 1
            print(f"  ✗ failed:  {ev.get('summary')}  ({e})")
    print()
    print(f"Done. Deleted {deleted}, failed {failed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
