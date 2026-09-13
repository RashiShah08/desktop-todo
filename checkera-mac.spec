# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Checkera on macOS.

Run on a Mac from the project root:
    pyinstaller --noconfirm checkera-mac.spec

Produces dist/Checkera.app — a single app bundle. Users drag it into
Applications, right-click → Open the first time (Gatekeeper warning),
then double-click normally on every subsequent launch."""
from pathlib import Path

PROJECT = Path('.').resolve()
block_cipher = None


a = Analysis(
    ['widget.py'],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'webview',
        'webview.platforms.cocoa',
        'pystray',
        'pystray._darwin',           # macOS tray backend
        'keyboard',
        'feedparser',
        'requests',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'googleapiclient.errors',
        # PyObjC bindings used by macos_integration.py
        'AppKit',
        'Foundation',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'PySide2', 'PyQt5', 'PyQt6',
        'pytest', 'unittest',
        'winotify',                   # Windows-only
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
    name='Checkera',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,                 # both Intel + Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Checkera',
)

# Wrap the collection in a proper .app bundle
app = BUNDLE(
    coll,
    name='Checkera.app',
    icon='assets/checkera.icns',
    bundle_identifier='com.checkera.app',
    info_plist={
        'CFBundleName': 'Checkera',
        'CFBundleDisplayName': 'Checkera',
        'CFBundleIdentifier': 'com.checkera.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        # Tells macOS this is a regular GUI app (no dock-hide weirdness)
        'LSUIElement': False,
        'NSHighResolutionCapable': True,
        # Required when using PyObjC + global event taps for hotkeys.
        # The user grants Input Monitoring permission on first hotkey use.
        'NSAppleEventsUsageDescription': 'Checkera shows desktop notifications when your tasks are due.',
    },
)
