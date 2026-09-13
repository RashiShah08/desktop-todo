"""macOS integration via PyObjC.

Mirrors the contracts in windows_integration.py but uses Cocoa APIs:

  exclude_from_capture_by_title(title)
      → NSWindow.setSharingType_(NSWindowSharingNone)
        — hides the window from screencapture/QuickTime/Zoom/Meet/Teams.

  set_app_icon(icns_path)
      → NSApplication.setApplicationIconImage_(NSImage)
        — replaces the dock + cmd-tab icon (per-process, not per-window).

Loaded lazily so the rest of the app keeps working if PyObjC isn't
available (development on a non-Mac, missing wheels, etc.)."""
from __future__ import annotations

import sys
from typing import Optional


IS_MAC = sys.platform == "darwin"

# PyObjC imports — only on Mac, and only when actually called
_appkit = None
_loaded = False


def _load_appkit():
    """Import AppKit lazily. Returns the module or None on failure."""
    global _appkit, _loaded
    if _loaded:
        return _appkit
    _loaded = True
    if not IS_MAC:
        return None
    try:
        import AppKit
        _appkit = AppKit
    except Exception as e:
        print(f"[mac] AppKit import failed: {e}", file=sys.stderr)
        _appkit = None
    return _appkit


def _find_window_by_title(title: str):
    """Return the NSWindow whose title matches, or None."""
    appkit = _load_appkit()
    if appkit is None:
        return None
    try:
        app = appkit.NSApplication.sharedApplication()
        for w in app.windows():
            try:
                if w.title() == title:
                    return w
            except Exception:
                continue
    except Exception as e:
        print(f"[mac] window enumeration failed: {e}", file=sys.stderr)
    return None


def exclude_from_capture_by_title(title: str) -> bool:
    """Make a window invisible to screen-capture/sharing tools."""
    appkit = _load_appkit()
    if appkit is None:
        return False
    win = _find_window_by_title(title)
    if win is None:
        return False
    try:
        # NSWindowSharingNone = 0 — fully hidden from capture
        win.setSharingType_(0)
        return True
    except Exception as e:
        print(f"[mac] setSharingType failed: {e}", file=sys.stderr)
        return False


def include_in_capture_by_title(title: str) -> bool:
    """Restore default screen-capture visibility."""
    appkit = _load_appkit()
    if appkit is None:
        return False
    win = _find_window_by_title(title)
    if win is None:
        return False
    try:
        # NSWindowSharingReadOnly = 1 — visible to capture (default)
        win.setSharingType_(1)
        return True
    except Exception:
        return False


def set_app_icon(icon_path: str) -> bool:
    """Replace the running app's dock + cmd-tab icon. On macOS this is a
    PROCESS-LEVEL setting, not per-window — one call updates everything.

    Accepts .icns, .png, or any format NSImage can read."""
    appkit = _load_appkit()
    if appkit is None:
        return False
    try:
        # initByReferencingFile loads lazily; safer than initWithContentsOfFile
        img = appkit.NSImage.alloc().initByReferencingFile_(icon_path)
        if img is None or not img.isValid():
            return False
        appkit.NSApplication.sharedApplication().setApplicationIconImage_(img)
        return True
    except Exception as e:
        print(f"[mac] set_app_icon failed: {e}", file=sys.stderr)
        return False
