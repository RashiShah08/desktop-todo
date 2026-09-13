# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Checkera.

Run on Windows from the project root:
    pyinstaller --noconfirm checkera.spec

Produces a folder distribution at dist/Checkera/ that contains:
    Checkera.exe
    _internal/          ← bundled Python + DLLs (don't open, don't move)
    frontend/           ← UI assets
    assets/             ← icons

To distribute, zip the entire dist/Checkera folder. Users unzip it anywhere
and double-click Checkera.exe — no Python install required.

Two folders the user creates on their machine (auto-created on first run):
    data/               ← their todos.json
    cache/              ← gcal + news caches
And two files they manage themselves:
    credentials.json    ← shared Google OAuth client (shipped with the app)
    token.json          ← per-user, created when they sign in
"""
from pathlib import Path

PROJECT = Path('.').resolve()
block_cipher = None


a = Analysis(
    ['widget.py'],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),    # HTML / CSS / JS / images for the UI
        ('assets', 'assets'),        # icons, .ico, wordmark
    ],
    # PyInstaller's static analyzer can't see dynamic imports from these
    # libraries — list them explicitly so they end up in the bundle.
    hiddenimports=[
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'pystray',
        'pystray._win32',
        'keyboard',
        'winotify',
        'feedparser',
        'requests',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'googleapiclient.errors',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Big libs we definitely don't use — keep the bundle slim
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'PySide2', 'PyQt5', 'PyQt6',
        'pytest', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Checkera',                 # → Checkera.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX often trips antivirus heuristics
    console=False,                   # GUI app, no console window flash
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/checkera.ico',      # baked-in .exe file icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Checkera',                 # → dist/Checkera/
)
