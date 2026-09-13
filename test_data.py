"""Self-tests for data.py. Run: python3 test_data.py
Tests the data layer in isolation (no UI, no Windows deps needed)."""
import json
import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from data import TodoStore, Task  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        FAILS.append(msg)


def section(title):
    print(f"\n=== {title} ===")


def tmp_store():
    d = tempfile.mkdtemp(prefix="todotest-")
    return TodoStore(Path(d) / "todos.json"), d


def test_add_and_get():
    section("add + get")
    store, d = tmp_store()
    try:
        t = store.add_task("Buy milk", "personal", priority="medium",
                           due_date="2026-05-20", due_time="18:00")
        check(t.name == "Buy milk", "name preserved")
        check(t.category == "personal", "category preserved")
        check(t.priority == "medium", "priority preserved")
        check(t.id is not None and len(t.id) > 10, "uuid assigned")
        check(t.completed is False, "starts not completed")
        check(t.archived is False, "starts not archived")
        fetched = store.get_task(t.id)
        check(fetched is not None and fetched.name == "Buy milk", "get_task works")
        check(store.get_task("nope") is None, "missing id returns None")
    finally:
        shutil.rmtree(d)


def test_validation():
    section("validation")
    store, d = tmp_store()
    try:
        try:
            store.add_task("X", "bad_cat")
            check(False, "bad category should raise")
        except ValueError:
            check(True, "bad category raises ValueError")
        try:
            store.add_task("X", "work", priority="urgent")
            check(False, "bad priority should raise")
        except ValueError:
            check(True, "bad priority raises ValueError")
        t = store.add_task("X", "work")
        try:
            store.edit_task(t.id, category="nope")
            check(False, "edit with bad category should raise")
        except ValueError:
            check(True, "edit_task validates category")
        try:
            store.edit_task(t.id, completed=True)
            check(False, "should not allow editing 'completed' via edit_task")
        except ValueError:
            check(True, "edit_task rejects disallowed field")
    finally:
        shutil.rmtree(d)


def test_edit():
    section("edit")
    store, d = tmp_store()
    try:
        t = store.add_task("Old name", "work")
        edited = store.edit_task(t.id, name="New name", priority="high",
                                 category="learning")
        check(edited.name == "New name", "name updated")
        check(edited.priority == "high", "priority updated")
        check(edited.category == "learning", "category updated")
        # Reload from disk to confirm persistence
        store2 = TodoStore(store.path)
        again = store2.get_task(t.id)
        check(again.name == "New name", "edit persisted to disk")
    finally:
        shutil.rmtree(d)


def test_toggle_and_archive():
    section("toggle complete + auto-archive")
    store, d = tmp_store()
    try:
        t = store.add_task("Task A", "work")
        result = store.toggle_complete(t.id)
        check(result.completed is True, "becomes completed on toggle")
        check(result.archived is True, "auto-archives when completed")
        check(result.completed_at is not None, "completed_at set")
        check(t.id not in [a.id for a in store.active_tasks()],
              "no longer in active")
        check(t.id in [a.id for a in store.archived_tasks()], "in archive")
        # Toggle back
        result2 = store.toggle_complete(t.id)
        check(result2.completed is False, "un-completes")
        check(result2.archived is False, "un-archives")
    finally:
        shutil.rmtree(d)


def test_unarchive():
    section("unarchive")
    store, d = tmp_store()
    try:
        t = store.add_task("Task A", "work")
        store.toggle_complete(t.id)
        store.unarchive_task(t.id)
        again = store.get_task(t.id)
        check(again.archived is False, "unarchived")
        check(again.completed is False, "un-completed when unarchived")
    finally:
        shutil.rmtree(d)


def test_delete():
    section("delete")
    store, d = tmp_store()
    try:
        t = store.add_task("Doomed", "personal")
        ok = store.delete_task(t.id)
        check(ok is True, "delete returns True")
        check(store.get_task(t.id) is None, "task gone")
        check(store.delete_task("nope") is False, "deleting missing returns False")
    finally:
        shutil.rmtree(d)


def test_overdue():
    section("overdue detection")
    store, d = tmp_store()
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        t1 = store.add_task("Overdue task", "work", due_date=yesterday)
        t2 = store.add_task("Future task", "work", due_date=tomorrow)
        t3 = store.add_task("No due date", "work")
        overdue_ids = {t.id for t in store.overdue_tasks()}
        check(t1.id in overdue_ids, "yesterday task is overdue")
        check(t2.id not in overdue_ids, "tomorrow task is not overdue")
        check(t3.id not in overdue_ids, "no-due task is not overdue")
        # Completed tasks not overdue
        store.toggle_complete(t1.id)
        check(t1.id not in {t.id for t in store.overdue_tasks()},
              "completed task no longer overdue")
    finally:
        shutil.rmtree(d)


def test_sort_and_group():
    section("sorting + grouping")
    store, d = tmp_store()
    try:
        t1 = store.add_task("A", "work", priority="low", due_date="2026-06-01")
        t2 = store.add_task("B", "personal", priority="high", due_date="2026-05-20")
        t3 = store.add_task("C", "learning")  # no due
        t4 = store.add_task("D", "work", priority="medium", due_date="2026-05-25")

        by_due = TodoStore.sort_by_due(store.active_tasks())
        names = [t.name for t in by_due]
        check(names[0] == "B", f"soonest first: got {names[0]}")
        check(names[-1] == "C", "no-due last")

        by_prio = TodoStore.sort_by_priority(store.active_tasks())
        first = by_prio[0]
        check(first.priority == "high", "high priority first")

        groups = TodoStore.group_by_category(store.active_tasks())
        check(set(groups.keys()) >= {"work", "personal", "learning"},
              "all categories present")
        check(len(groups["work"]) == 2, "work has 2 tasks")
        check(len(groups["personal"]) == 1, "personal has 1")
        check(len(groups["learning"]) == 1, "learning has 1")
    finally:
        shutil.rmtree(d)


def test_archive_cleanup():
    section("archive auto-clean")
    store, d = tmp_store()
    try:
        t1 = store.add_task("Old", "work")
        t2 = store.add_task("Recent", "work")
        store.toggle_complete(t1.id)
        store.toggle_complete(t2.id)
        # Manually backdate t1's completed_at to 40 days ago
        for raw in store._data["tasks"]:
            if raw["id"] == t1.id:
                raw["completed_at"] = (datetime.now() - timedelta(days=40)).isoformat()
        store._save()
        deleted = store.clean_old_archived(days=30)
        check(deleted == 1, f"deleted 1 old archived task (got {deleted})")
        check(store.get_task(t1.id) is None, "old task gone")
        check(store.get_task(t2.id) is not None, "recent task kept")
    finally:
        shutil.rmtree(d)


def test_persistence():
    section("save/reload persistence")
    d = tempfile.mkdtemp(prefix="todotest-")
    try:
        path = Path(d) / "todos.json"
        s1 = TodoStore(path)
        t = s1.add_task("Persistent", "work", priority="high", due_date="2026-12-01")
        s2 = TodoStore(path)
        again = s2.get_task(t.id)
        check(again is not None, "task survives reload")
        check(again.priority == "high", "fields survive reload")
        # Check JSON is valid + readable
        with open(path) as f:
            raw = json.load(f)
        check("tasks" in raw and "settings" in raw, "JSON shape correct")
    finally:
        shutil.rmtree(d)


def test_corrupt_recovery():
    section("corrupt file recovery")
    d = tempfile.mkdtemp(prefix="todotest-")
    try:
        path = Path(d) / "todos.json"
        path.write_text("{ not valid json")
        store = TodoStore(path)
        check(store.all_tasks() == [], "starts fresh on corrupt")
        backup = path.with_suffix(".json.corrupt")
        check(backup.exists(), "corrupt file backed up")
        # Should be able to add tasks normally
        store.add_task("New", "work")
        check(len(store.all_tasks()) == 1, "works after recovery")
    finally:
        shutil.rmtree(d)


def test_settings():
    section("settings")
    store, d = tmp_store()
    try:
        check(store.settings["user_name"] == "Rashi", "default user_name")
        check(store.settings["auto_clean_archive_days"] == 30, "default cleanup days")
        store.update_setting("last_news_fetch", "2026-05-15T08:00")
        # Reload and verify
        store2 = TodoStore(store.path)
        check(store2.settings["last_news_fetch"] == "2026-05-15T08:00",
              "settings persist")
    finally:
        shutil.rmtree(d)


def test_pending_reminders():
    section("pending reminders")
    store, d = tmp_store()
    try:
        past = (datetime.now() - timedelta(minutes=5)).replace(microsecond=0).isoformat(timespec="minutes")
        future = (datetime.now() + timedelta(hours=1)).replace(microsecond=0).isoformat(timespec="minutes")
        t1 = store.add_task("Should fire", "work", reminder_at=past)
        t2 = store.add_task("Future", "work", reminder_at=future)
        t3 = store.add_task("No reminder", "work")
        pending = store.pending_reminders()
        ids = {t.id for t in pending}
        check(t1.id in ids, "past reminder is pending")
        check(t2.id not in ids, "future reminder is not pending")
        check(t3.id not in ids, "no-reminder task not pending")
        # Mark reminded — should not appear again
        store.mark_reminded(t1.id)
        pending2 = store.pending_reminders()
        check(t1.id not in {t.id for t in pending2}, "reminded task drops out")
        check(store.get_task(t1.id).reminded is True, "reminded persisted")
        # Editing reminder_at should reset reminded
        new_past = (datetime.now() - timedelta(minutes=1)).replace(microsecond=0).isoformat(timespec="minutes")
        store.edit_task(t1.id, reminder_at=new_past)
        check(store.get_task(t1.id).reminded is False, "edit reminder resets reminded flag")
        # Completed reminders don't fire
        t4 = store.add_task("Done", "work", reminder_at=past)
        store.toggle_complete(t4.id)
        check(t4.id not in {t.id for t in store.pending_reminders()},
              "completed task's reminder doesn't fire")
    finally:
        shutil.rmtree(d)


def test_backward_compat_load():
    section("loads old JSON without 'reminded' field")
    d = tempfile.mkdtemp(prefix="todotest-")
    try:
        path = Path(d) / "todos.json"
        # Simulate JSON written by a pre-Phase-2 version (no 'reminded' key)
        old_data = {
            "tasks": [{
                "id": "abc-123",
                "name": "Legacy task",
                "category": "work",
                "priority": None,
                "due_date": None,
                "due_time": None,
                "reminder_at": None,
                "completed": False,
                "created_at": "2026-01-01T10:00:00",
                "completed_at": None,
                "archived": False,
                "gcal_event_id": None,
            }],
            "settings": {},
        }
        with open(path, "w") as f:
            json.dump(old_data, f)
        store = TodoStore(path)
        t = store.get_task("abc-123")
        check(t is not None, "loaded legacy task")
        check(t.reminded is False, "reminded defaults to False on load")
    finally:
        shutil.rmtree(d)


def test_due_datetime_parsing():
    section("due_datetime parsing")
    store, d = tmp_store()
    try:
        t = store.add_task("X", "work", due_date="2026-05-20", due_time="14:30")
        dt = t.due_datetime()
        check(dt == datetime(2026, 5, 20, 14, 30), f"date+time parsed (got {dt})")
        t2 = store.add_task("Y", "work", due_date="2026-05-20")
        dt2 = t2.due_datetime()
        check(dt2 is not None and dt2.year == 2026, "date-only parsed")
        t3 = store.add_task("Z", "work")
        check(t3.due_datetime() is None, "no due → None")
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    test_add_and_get()
    test_validation()
    test_edit()
    test_toggle_and_archive()
    test_unarchive()
    test_delete()
    test_overdue()
    test_sort_and_group()
    test_archive_cleanup()
    test_persistence()
    test_corrupt_recovery()
    test_settings()
    test_pending_reminders()
    test_backward_compat_load()
    test_due_datetime_parsing()
    print(f"\n{'─' * 40}")
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL PASS ✓")
