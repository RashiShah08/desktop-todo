@echo off
REM ────────────────────────────────────────────────────────────────
REM Build script for Checkera (Windows only).
REM Produces: dist\Checkera\  — zip this folder to distribute.
REM
REM Run from the project root:
REM     build.bat
REM
REM Requirements: Python 3.11+ on PATH, internet for the first run.
REM ────────────────────────────────────────────────────────────────

setlocal

echo.
echo [1/4] Cleaning previous build...
if exist build rmdir /S /Q build
if exist dist  rmdir /S /Q dist

echo.
echo [2/4] Installing runtime dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo.
    echo Failed installing requirements.txt — fix the error above, then re-run.
    pause
    exit /b 1
)

echo.
echo [3/4] Installing PyInstaller...
python -m pip install --quiet pyinstaller
if errorlevel 1 (
    echo PyInstaller install failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Building Checkera.exe...
python -m PyInstaller --noconfirm checkera.spec
if errorlevel 1 (
    echo.
    echo Build failed — scroll up for the PyInstaller error.
    pause
    exit /b 1
)

echo.
echo ────────────────────────────────────────────────────────────────
echo  Build complete.
echo.
echo  Output: dist\Checkera\Checkera.exe
echo.
echo  To distribute:
echo    1. Right-click the dist\Checkera folder
echo    2. Send to → Compressed (zipped) folder
echo    3. Send the resulting Checkera.zip to your users
echo.
echo  Each user just unzips and double-clicks Checkera.exe.
echo ────────────────────────────────────────────────────────────────
echo.
pause
