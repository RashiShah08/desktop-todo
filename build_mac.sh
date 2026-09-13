#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# Build script for Checkera (macOS only).
# Produces: dist/Checkera.app  — zip it (or wrap in a .dmg) to distribute.
#
# Run from the project root:
#     ./build_mac.sh
#
# Requirements: Python 3.11+ on PATH, internet for the first run.
# ────────────────────────────────────────────────────────────────
set -e

if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "build_mac.sh only runs on macOS (you're on $OSTYPE)."
    echo "Use build.bat on Windows."
    exit 1
fi

echo
echo "[1/4] Cleaning previous build..."
rm -rf build dist

echo
echo "[2/4] Installing runtime dependencies..."
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r requirements.txt

echo
echo "[3/4] Installing PyInstaller..."
python3 -m pip install --quiet pyinstaller

echo
echo "[4/4] Building Checkera.app..."
python3 -m PyInstaller --noconfirm checkera-mac.spec

echo
echo "────────────────────────────────────────────────────────────────"
echo "  Build complete."
echo
echo "  Output: dist/Checkera.app"
echo
echo "  Test it locally:"
echo "      open dist/Checkera.app"
echo
echo "  Distribute (option 1 — zip):"
echo "      cd dist && zip -r Checkera-mac.zip Checkera.app && cd .."
echo
echo "  Distribute (option 2 — .dmg, nicer UX for users):"
echo "      hdiutil create -volname Checkera -srcfolder dist/Checkera.app \\"
echo "                     -ov -format UDZO Checkera-mac.dmg"
echo
echo "  Each user drags Checkera.app to Applications, right-clicks Open"
echo "  on first launch, clicks Open in the warning dialog. Done."
echo "────────────────────────────────────────────────────────────────"
