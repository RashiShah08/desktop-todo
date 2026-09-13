"""Path-resolution helpers — works in both dev mode (`python widget.py`) and
when bundled as Checkera.exe via PyInstaller.

There are two roots an app like ours cares about:

  resource_root()  — read-only assets bundled with the program. The HTML/CSS
                     for the UI, the icon files, etc. Frozen → sys._MEIPASS.
                     Dev → the project folder.

  user_root()      — writable files the user owns or generates. The tasks
                     JSON, the GCal credentials/token, the news cache.
                     Frozen → the folder next to Checkera.exe (so the user
                     can drop credentials.json there, and so token.json /
                     todos.json persist across runs).
                     Dev → the project folder.

The split matters for PyInstaller onefile mode where _MEIPASS is a TEMP
directory recreated each launch — anything written there would vanish."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_root() -> Path:
    """Where read-only bundled assets live."""
    if is_frozen():
        # PyInstaller — onefile: _MEIPASS = temp extracted dir
        #               onedir: _MEIPASS = the dir containing the .exe
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_root() -> Path:
    """Where the user's mutable data lives.

    Windows (frozen)  → folder containing Checkera.exe (visible, draggable)
    macOS   (frozen)  → ~/Library/Application Support/Checkera   (Apple's
                        convention; can't write inside the .app bundle
                        because Gatekeeper blocks it on signed apps)
    Dev mode (either) → project folder
    """
    if is_frozen():
        if sys.platform == "darwin":
            home = Path.home() / "Library" / "Application Support" / "Checkera"
            home.mkdir(parents=True, exist_ok=True)
            return home
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
