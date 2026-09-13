"""Install / uninstall Checkera's auto-launch on Windows OR macOS.

Usage:
    python startup.py install     # add it
    python startup.py uninstall   # remove it
    python startup.py status      # show current state

Windows: creates a .lnk in %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup
macOS:   writes a LaunchAgent plist at ~/Library/LaunchAgents/com.checkera.plist
         and loads it via launchctl."""
from __future__ import annotations

import os
import subprocess
import sys
import shutil
from pathlib import Path


SHORTCUT_NAME = "Checkera.lnk"


def _startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable not set.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_folder() / SHORTCUT_NAME


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _find_pythonw() -> Path:
    """Prefer pythonw.exe (no console window) over python.exe."""
    base = Path(sys.executable).parent
    pythonw = base / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    # Fall back to whatever invoked us
    return Path(sys.executable)


def _win_target_and_args() -> tuple[Path, str]:
    """Resolve what the Startup shortcut should launch.

    • Packaged app (running as Checkera.exe via PyInstaller): point straight
      at that .exe, no arguments — this is what end users actually have.
    • Dev checkout (running via `python widget.py`): fall back to
      pythonw.exe + the widget.py path, same as before.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable), ""
    widget = _project_root() / "widget.py"
    if not widget.exists():
        raise FileNotFoundError(f"widget.py not found at {widget}")
    return _find_pythonw(), f'"{widget}"'


def install() -> Path:
    """Create the Startup shortcut. Returns the path created."""
    target, args = _win_target_and_args()
    # Frozen: run from the .exe's own folder (so relative frontend/assets
    # resolve). Dev: run from the project root, as before.
    workdir = target.parent if getattr(sys, "frozen", False) else _project_root()

    startup_dir = _startup_folder()
    startup_dir.mkdir(parents=True, exist_ok=True)
    lnk = _shortcut_path()

    # Build via PowerShell — avoids pywin32 dependency
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath = '{target}'
$sc.Arguments = '{args}'
$sc.WorkingDirectory = '{workdir}'
$sc.WindowStyle = 7
$sc.Description = 'Checkera — floating to-do widget'
$sc.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell failed: {result.stderr.strip()}")
    return lnk


def uninstall() -> bool:
    """Remove the shortcut. Returns True if removed."""
    lnk = _shortcut_path()
    if lnk.exists():
        lnk.unlink()
        return True
    return False


def status() -> dict:
    lnk = _shortcut_path()
    return {
        "installed": lnk.exists(),
        "shortcut_path": str(lnk),
        "startup_folder": str(_startup_folder()),
    }


# ─── macOS LaunchAgent ────────────────────────────────────────────
MAC_LABEL = "com.checkera"
MAC_PLIST_NAME = f"{MAC_LABEL}.plist"


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / MAC_PLIST_NAME


def _mac_install() -> Path:
    """Write a LaunchAgent that runs Checkera on every login."""
    # Resolve the executable to launch:
    #   • If we're frozen (running as Checkera.app), prefer the .app binary
    #   • Otherwise fall back to `python widget.py`
    exe_path: str
    args: list
    if getattr(sys, "frozen", False):
        # Walk up from the .app binary to the .app bundle root
        exe_path = sys.executable
        args = [exe_path]
    else:
        widget = _project_root() / "widget.py"
        if not widget.exists():
            raise FileNotFoundError(f"widget.py not found at {widget}")
        exe_path = sys.executable
        args = [exe_path, str(widget)]

    program_args = "".join(f"    <string>{a}</string>\n" for a in args)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MAC_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    # Load it so it runs every login from now on
    subprocess.run(["launchctl", "load", "-w", str(path)],
                   check=False, capture_output=True)
    return path


def _mac_uninstall() -> bool:
    path = _mac_plist_path()
    if not path.exists():
        return False
    subprocess.run(["launchctl", "unload", "-w", str(path)],
                   check=False, capture_output=True)
    path.unlink()
    return True


def _mac_status() -> dict:
    path = _mac_plist_path()
    return {
        "installed": path.exists(),
        "shortcut_path": str(path),
        "startup_folder": str(path.parent),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    is_mac = sys.platform == "darwin"
    is_win = sys.platform == "win32"
    if not (is_mac or is_win):
        print(f"Auto-startup installer only supports Windows and macOS "
              f"(you're on {sys.platform}).")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "install":
        path = _mac_install() if is_mac else install()
        print(f"Installed: {path}")
        print("Checkera will launch automatically next time you sign in.")
    elif cmd == "uninstall":
        removed = _mac_uninstall() if is_mac else uninstall()
        print("Removed." if removed else "Was not installed.")
    elif cmd == "status":
        s = _mac_status() if is_mac else status()
        print(f"Installed: {s['installed']}")
        print(f"Path:      {s['shortcut_path']}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
