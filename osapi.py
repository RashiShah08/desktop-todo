"""Cross-platform OS integration shim.

Picks the right backend at import time:
  • Windows → windows_integration.py (Win32 via ctypes)
  • macOS   → macos_integration.py   (Cocoa via PyObjC)
  • else    → all no-ops so the app still runs (without OS-level features)

Every function here takes a window TITLE (string) instead of an OS-specific
handle, so the caller (widget.py) doesn't need to know whether we're on
Windows (hwnd) or Mac (NSWindow). The shim resolves the handle internally.
"""
from __future__ import annotations

import sys

# ── Windows ─────────────────────────────────────────────────────────
if sys.platform == "win32":
    import windows_integration as _impl

    def _resolve_hwnd(title: str):
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            u32.FindWindowW.restype = wintypes.HWND
            return u32.FindWindowW(None, title)
        except Exception:
            return None

    def set_app_user_model_id(aumid: str) -> bool:
        return _impl.set_app_user_model_id(aumid)

    def exclude_from_capture(title: str) -> bool:
        hwnd = _resolve_hwnd(title)
        return bool(hwnd and _impl.exclude_from_capture(hwnd))

    def set_window_icon(title: str, icon_path: str) -> bool:
        hwnd = _resolve_hwnd(title)
        return bool(hwnd and _impl.set_window_icon(hwnd, icon_path))

# ── macOS ───────────────────────────────────────────────────────────
elif sys.platform == "darwin":
    import macos_integration as _impl

    def set_app_user_model_id(aumid: str) -> bool:
        # Handled via the .app's Info.plist (CFBundleIdentifier) when bundled.
        # No runtime call needed; return True so callers don't see a failure.
        return True

    def exclude_from_capture(title: str) -> bool:
        return _impl.exclude_from_capture_by_title(title)

    def set_window_icon(title: str, icon_path: str) -> bool:
        # On macOS the icon is per-application, not per-window — set once.
        return _impl.set_app_icon(icon_path)

# ── Linux / fallback ───────────────────────────────────────────────
else:
    def set_app_user_model_id(aumid: str) -> bool: return False
    def exclude_from_capture(title: str) -> bool: return False
    def set_window_icon(title: str, icon_path: str) -> bool: return False
