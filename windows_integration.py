"""Windows-only integrations: desktop-layer pinning + screen-capture exclusion.

All ctypes calls go through user32.dll. Nothing here requires admin
privileges or touches the registry or system files. If anything fails the
functions return False and the app keeps working in "regular window" mode.

References:
  • WorkerW pinning is the same technique Rainmeter, Wallpaper Engine, and
    other desktop widget tools use. Send Progman a magic message to spawn
    a WorkerW, then SetParent our window to it.
  • SetWindowDisplayAffinity / WDA_EXCLUDEFROMCAPTURE: Windows 10 2004+.
    Makes a window invisible to screen-capture APIs while still showing
    normally on the user's screen — perfect for hiding the widget during
    Zoom / Teams / Meet / OBS screen sharing."""
from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes
from typing import Optional


IS_WINDOWS = sys.platform == "win32"


# ─────────────────────────────────────────────────────────────────────
# Win32 plumbing
# ─────────────────────────────────────────────────────────────────────

if IS_WINDOWS:
    user32 = ctypes.windll.user32

    # Function prototypes (best-effort: helps ctypes pick correct ABI on x64)
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                     wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.SendMessageTimeoutW.restype = ctypes.c_void_p
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT,
                                           ctypes.POINTER(wintypes.DWORD)]
    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

# Constants
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

SW_HIDE = 0
SW_SHOWNA = 8      # show without stealing focus

# WDA_EXCLUDEFROMCAPTURE = 0x11 (Windows 10 2004+). 0x1 is older WDA_MONITOR
# which makes the window black on capture; 0x11 makes it fully invisible.
WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11

# Magic Progman message — tells Explorer to spawn a WorkerW between the
# wallpaper and the desktop icons. Not officially documented but stable
# since Windows 7. The same value Rainmeter / Wallpaper Engine use.
WM_SPAWN_WORKERW = 0x052C


# ─────────────────────────────────────────────────────────────────────
# HWND helpers
# ─────────────────────────────────────────────────────────────────────

def tk_hwnd(tk_window) -> Optional[int]:
    """Get the HWND of a Tk toplevel window."""
    if not IS_WINDOWS:
        return None
    try:
        tk_window.update_idletasks()
        # frame() returns the outer Win32 window — the toplevel HWND we want
        frame_hex = tk_window.frame()
        return int(frame_hex, 16)
    except Exception as e:
        print(f"[win] tk_hwnd failed: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────────────────────────────
# Screen-capture exclusion (Zoom / Teams / Meet / OBS hide)
# ─────────────────────────────────────────────────────────────────────

def set_app_user_model_id(aumid: str) -> bool:
    """Tell Windows this process is its own app — not just another python.exe
    invocation. Without this, the taskbar groups our window under Python and
    uses Python's icon regardless of WM_SETICON. Must be called BEFORE the
    first window is created."""
    if not IS_WINDOWS:
        return False
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
        shell32.SetCurrentProcessExplicitAppUserModelID(aumid)
        return True
    except Exception as e:
        print(f"[win] set_app_user_model_id failed: {e}", file=sys.stderr)
        return False


def set_window_icon(hwnd: int, ico_path: str) -> bool:
    """Replace the window's title-bar + taskbar icon with the given .ico file.
    Without this, PyWebView windows show the Python interpreter's icon."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        # LoadImageW: load an .ico from a file
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                      wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]

        # Load a small (16/32) and large (32/48) variant from the multi-res .ico
        small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16,
                                  LR_LOADFROMFILE)
        big   = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32,
                                  LR_LOADFROMFILE)
        if not small and not big:
            return False
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        return True
    except Exception as e:
        print(f"[win] set_window_icon failed: {e}", file=sys.stderr)
        return False


def exclude_from_capture(hwnd: int) -> bool:
    """Hide window from screen-capture / screen-share. Returns True on success.
    Requires Windows 10 version 2004 or newer."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        # SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        result = user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd),
                                                 wintypes.DWORD(WDA_EXCLUDEFROMCAPTURE))
        return bool(result)
    except (AttributeError, OSError) as e:
        print(f"[win] exclude_from_capture failed: {e}", file=sys.stderr)
        return False


def include_in_capture(hwnd: int) -> bool:
    """Undo exclude_from_capture — window visible to screen capture again."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        result = user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd),
                                                 wintypes.DWORD(WDA_NONE))
        return bool(result)
    except (AttributeError, OSError):
        return False


def hide_from_taskbar(hwnd: int) -> bool:
    """Drop the window's taskbar button (and its Alt-Tab entry) by making it a
    tool window — the standard trick for desktop widgets that live in the tray.

    Windows only picks up an WS_EX_TOOLWINDOW change reliably while the window
    is hidden, so the restyle is wrapped in a hide/show cycle. SW_SHOWNA brings
    it back without stealing focus from whatever the user is doing."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        # GetWindowLongPtrW only exists in 64-bit user32; 32-bit uses the
        # non-Ptr variant. Pick whichever this interpreter actually has.
        get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get_long.restype = ctypes.c_ssize_t
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        set_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

        h = wintypes.HWND(hwnd)
        style = get_long(h, GWL_EXSTYLE)
        new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if new_style == style:
            return True
        user32.ShowWindow(h, SW_HIDE)
        set_long(h, GWL_EXSTYLE, new_style)
        user32.ShowWindow(h, SW_SHOWNA)
        return True
    except Exception as e:
        print(f"[win] hide_from_taskbar failed: {e}", file=sys.stderr)
        return False


# ─────────────────────────────────────────────────────────────────────
# WorkerW pinning
# ─────────────────────────────────────────────────────────────────────

def _find_workerw() -> Optional[int]:
    """Find the WorkerW window that sits behind the desktop icons.
    Returns its HWND, or None if not found."""
    if not IS_WINDOWS:
        return None
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None
    # Ask Progman to spawn a WorkerW between wallpaper + icons.
    # Safe to call repeatedly — if one already exists, Windows reuses it.
    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(progman, WM_SPAWN_WORKERW, 0, 0, 0, 1000,
                               ctypes.byref(result))

    # Enumerate top-level windows looking for a WorkerW whose sibling
    # holds the SHELLDLL_DefView (the desktop icons surface). The previous
    # WorkerW (without that child) is the one we want — it's painted
    # between the wallpaper and the icons.
    target = [None]

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        # Check this WorkerW has DefView child
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            # The WorkerW *next* to this one (sibling) is our target
            buf = ctypes.create_unicode_buffer(64)
            sibling = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if sibling:
                # Confirm sibling class
                user32.GetClassNameW(sibling, buf, 64)
                if buf.value == "WorkerW":
                    target[0] = sibling
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return target[0]


def pin_to_desktop(hwnd: int) -> bool:
    """Reparent the given window onto the desktop's WorkerW layer.
    Result: window appears at desktop level — apps cover it, it survives
    Win+D, no taskbar entry. Falls back to HWND_BOTTOM z-order if WorkerW
    parenting can't be found.

    Returns True if any pinning method succeeded."""
    if not IS_WINDOWS or not hwnd:
        return False

    workerw = _find_workerw()
    if workerw:
        try:
            old_parent = user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(workerw))
            if old_parent:
                return True
        except OSError as e:
            print(f"[win] SetParent to WorkerW failed: {e}", file=sys.stderr)

    # Fallback: just send to back, no-activate
    try:
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_BOTTOM),
                            0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return True
    except OSError:
        return False


def unpin_from_desktop(hwnd: int) -> bool:
    """Reverse pin_to_desktop — bring window back to the regular layer
    so it can float / be topmost / get user interaction normally."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(0))
        return True
    except OSError as e:
        print(f"[win] SetParent(None) failed: {e}", file=sys.stderr)
        return False


def bring_to_front_topmost(hwnd: int) -> bool:
    """Make the window appear on top of everything and receive focus."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
        return True
    except OSError:
        return False


def clear_topmost(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_NOTOPMOST),
                            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True
    except OSError:
        return False
