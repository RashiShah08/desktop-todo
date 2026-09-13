"""Tests the pure-Python helpers in ui.py by stubbing the GUI imports.
Run: python3 test_ui_helpers.py
This is what test_data.py is for the data layer — it isolates testable logic
from anything that needs a display."""
import sys
import types
from datetime import datetime, date
from pathlib import Path


def install_stubs():
    """Inject fake customtkinter / tkinter modules so ui.py imports without a display."""
    class _Stub:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, name): return _Stub
        def __call__(self, *a, **kw): return _Stub()

    stub_mod = types.ModuleType("customtkinter")
    for name in ("CTk", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry",
                 "CTkCheckBox", "CTkRadioButton", "CTkComboBox",
                 "CTkScrollableFrame", "CTkToplevel", "StringVar", "BooleanVar",
                 "set_appearance_mode", "set_default_color_theme"):
        setattr(stub_mod, name, _Stub)
    sys.modules["customtkinter"] = stub_mod

    # tkinter — provide the bare bones
    if "tkinter" not in sys.modules:
        tk = types.ModuleType("tkinter")
        tk.Canvas = _Stub
        tk.messagebox = types.ModuleType("tkinter.messagebox")
        tk.messagebox.showwarning = lambda *a, **kw: None
        tk.messagebox.askyesno = lambda *a, **kw: True
        tk.messagebox.showinfo = lambda *a, **kw: None
        tk.messagebox.showerror = lambda *a, **kw: None
        sys.modules["tkinter"] = tk
        sys.modules["tkinter.messagebox"] = tk.messagebox

    # tkcalendar stub
    tkcal = types.ModuleType("tkcalendar")
    tkcal.DateEntry = _Stub
    sys.modules["tkcalendar"] = tkcal


install_stubs()
sys.path.insert(0, str(Path(__file__).parent))
import ui  # noqa: E402


FAILS = []


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILS.append(msg)


def test_fmt_indian_date():
    print("\n=== fmt_indian_date ===")
    check(ui.fmt_indian_date(date(2026, 5, 20)) == "20/05/2026", "DD/MM/YYYY format")
    check(ui.fmt_indian_date(date(2026, 1, 1)) == "01/01/2026", "zero-pads")


def test_parse_indian_date():
    print("\n=== parse_indian_date ===")
    check(ui.parse_indian_date("20/05/2026") == date(2026, 5, 20), "DD/MM/YYYY")
    check(ui.parse_indian_date("20-05-2026") == date(2026, 5, 20), "DD-MM-YYYY")
    check(ui.parse_indian_date("2026-05-20") == date(2026, 5, 20), "ISO fallback")
    check(ui.parse_indian_date("") is None, "empty → None")
    check(ui.parse_indian_date("not a date") is None, "garbage → None")
    check(ui.parse_indian_date("  20/05/2026  ") == date(2026, 5, 20), "whitespace tolerated")
    # Indian-style 32/13/2026 should fail
    check(ui.parse_indian_date("32/13/2026") is None, "invalid date → None")


def test_time_12h_to_24h():
    print("\n=== time_12h_to_24h ===")
    check(ui.time_12h_to_24h("2", "30", "PM") == "14:30", "2:30 PM → 14:30")
    check(ui.time_12h_to_24h("2", "30", "AM") == "02:30", "2:30 AM → 02:30")
    check(ui.time_12h_to_24h("12", "00", "AM") == "00:00", "12:00 AM → 00:00 (midnight)")
    check(ui.time_12h_to_24h("12", "00", "PM") == "12:00", "12:00 PM → 12:00 (noon)")
    check(ui.time_12h_to_24h("12", "30", "PM") == "12:30", "12:30 PM → 12:30")
    check(ui.time_12h_to_24h("12", "30", "AM") == "00:30", "12:30 AM → 00:30")
    check(ui.time_12h_to_24h("11", "59", "PM") == "23:59", "11:59 PM → 23:59")
    check(ui.time_12h_to_24h("25", "30", "PM") is None, "invalid hour → None")
    check(ui.time_12h_to_24h("5", "75", "PM") is None, "invalid minute → None")
    check(ui.time_12h_to_24h("0", "0", "AM") is None, "hour 0 invalid in 12h")
    check(ui.time_12h_to_24h("abc", "30", "PM") is None, "non-numeric hour → None")


def test_time_24h_to_12h():
    print("\n=== time_24h_to_12h ===")
    check(ui.time_24h_to_12h("14:30") == ("2", "30", "PM"), "14:30 → 2:30 PM")
    check(ui.time_24h_to_12h("00:00") == ("12", "00", "AM"), "00:00 → 12:00 AM")
    check(ui.time_24h_to_12h("12:00") == ("12", "00", "PM"), "12:00 → 12:00 PM")
    check(ui.time_24h_to_12h("23:59") == ("11", "59", "PM"), "23:59 → 11:59 PM")
    check(ui.time_24h_to_12h("09:05") == ("9", "05", "AM"), "09:05 → 9:05 AM")
    check(ui.time_24h_to_12h(None) == ("9", "00", "AM"), "None → defaults")
    check(ui.time_24h_to_12h("bad") == ("9", "00", "AM"), "garbage → defaults")
    check(ui.time_24h_to_12h("") == ("9", "00", "AM"), "empty → defaults")


def test_greeting():
    print("\n=== greeting_for ===")
    m_g, m_t = ui.greeting_for(datetime(2026, 5, 15, 8, 0), "Rashi")
    a_g, a_t = ui.greeting_for(datetime(2026, 5, 15, 14, 0), "Rashi")
    e_g, e_t = ui.greeting_for(datetime(2026, 5, 15, 20, 0), "Rashi")
    check("Rashi" in m_g, f"morning greeting includes name: {m_g!r}")
    check("Rashi" in a_g, f"afternoon greeting includes name: {a_g!r}")
    check("Rashi" in e_g, f"evening greeting includes name: {e_g!r}")
    check(bool(m_t) and isinstance(m_t, str), "morning tagline returned")
    check(bool(a_t) and isinstance(a_t, str), "afternoon tagline returned")
    check(bool(e_t) and isinstance(e_t, str), "evening tagline returned")
    check(m_g.lower().startswith(("good morning", "hi", "morning", "hello")),
          f"morning greeting variant: {m_g!r}")
    # Deterministic within a day
    g1 = ui.greeting_for(datetime(2026, 5, 15, 8, 0), "Rashi")
    g2 = ui.greeting_for(datetime(2026, 5, 15, 9, 30), "Rashi")
    check(g1 == g2, "same greeting/tagline throughout a morning")


def test_time_roundtrip():
    print("\n=== time round-trip ===")
    cases = [("14:30"), ("00:00"), ("12:00"), ("12:30"), ("09:05"), ("23:59"), ("11:00")]
    for c in cases:
        h, m, ap = ui.time_24h_to_12h(c)
        back = ui.time_12h_to_24h(h, m, ap)
        check(back == c, f"{c} → ({h},{m},{ap}) → {back}")


if __name__ == "__main__":
    test_fmt_indian_date()
    test_parse_indian_date()
    test_time_12h_to_24h()
    test_time_24h_to_12h()
    test_greeting()
    test_time_roundtrip()
    print("\n" + "─" * 40)
    if FAILS:
        print(f"FAILED ({len(FAILS)}):")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL PASS ✓")
