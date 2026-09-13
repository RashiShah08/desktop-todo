"""System tray icon. Right-click menu to show/hide/quit."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception:
    # pystray can raise non-ImportError on Linux when GTK isn't present;
    # we catch broadly so the rest of the app keeps working anywhere.
    HAS_TRAY = False
    pystray = None
    Image = None
    ImageDraw = None


def _load_icon_image():
    """Use the Checkera mark for the tray. Falls back to the older mascot if
    that's all that's around, then to a generated swatch as a last resort."""
    if Image is None:
        return None
    from paths import resource_root
    assets = resource_root() / "assets"
    for candidate in ("checkera-icon-64.png", "checkera-icon.png", "mascot.png"):
        p = assets / candidate
        if p.exists():
            try:
                return Image.open(p)
            except Exception:
                continue
    # Last-ditch fallback: a tiny orange terracotta tile
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, size - 4, size - 4), radius=12,
                        fill=(212, 132, 90, 255))
    return img


class TrayController:
    """Wraps pystray.Icon. Runs in a background thread so Tk can own the main loop."""

    def __init__(self, on_show: Callable, on_hide: Callable, on_add: Callable,
                 on_quit: Callable):
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_add = on_add
        self.on_quit = on_quit
        self.icon: Optional["pystray.Icon"] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if not HAS_TRAY:
            print("[tray] pystray not available — system tray disabled.")
            return
        image = _load_icon_image()
        if image is None:
            print("[tray] no image available — system tray disabled.")
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show widget", lambda *a: self.on_show(), default=True),
                pystray.MenuItem("Hide widget", lambda *a: self.on_hide()),
                pystray.MenuItem("Add task…", lambda *a: self.on_add()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *a: self._quit()),
            )
            self.icon = pystray.Icon("checkera", image, "Checkera", menu)
            self.thread = threading.Thread(target=self.icon.run, daemon=True)
            self.thread.start()
        except Exception as e:
            print(f"[tray] failed to start: {e}")

    def _quit(self):
        try:
            if self.icon:
                self.icon.stop()
        finally:
            self.on_quit()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
