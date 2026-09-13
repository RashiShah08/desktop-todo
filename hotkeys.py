"""Global hotkey registration.

Hotkeys:
  Ctrl+Shift+T  — toggle floating-on-top mode (bring widget forward)
  Ctrl+Shift+H  — toggle widget visibility (screen-share emergency)

We use the `keyboard` library which works on Windows without admin rights.
Callbacks fire on a background thread, so they trampoline through
`tk_window.after(0, ...)` onto the UI thread before touching Tk."""
from __future__ import annotations

import sys
from typing import Callable

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


HOTKEY_TOGGLE_FLOAT = "ctrl+shift+t"
HOTKEY_TOGGLE_HIDE = "ctrl+shift+h"
HOTKEY_QUICK_ADD = "ctrl+shift+n"
HOTKEY_TOGGLE_FOCUS = "ctrl+shift+f"


class HotkeyManager:
    def __init__(self, tk_window):
        self.tk = tk_window
        self._registered = []

    def register(self, combo: str, on_press: Callable) -> bool:
        """Register a global hotkey. Returns True on success."""
        if not HAS_KEYBOARD:
            print("[hotkeys] keyboard module not installed — global hotkeys disabled.",
                  file=sys.stderr)
            return False
        try:
            # `keyboard` calls on a worker thread; bounce to Tk's main thread
            def _proxy():
                self.tk.after(0, on_press)
            keyboard.add_hotkey(combo, _proxy, suppress=False)
            self._registered.append(combo)
            return True
        except Exception as e:
            print(f"[hotkeys] failed to register {combo}: {e}", file=sys.stderr)
            return False

    def unregister_all(self):
        if not HAS_KEYBOARD:
            return
        for combo in self._registered:
            try:
                keyboard.remove_hotkey(combo)
            except (KeyError, ValueError):
                pass
        self._registered.clear()
