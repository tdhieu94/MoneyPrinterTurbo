@echo off
setlocal
rem One-time setup for the desktop app: installs uv if it is missing, installs
rem the Python dependencies, and puts a shortcut on the Desktop. Safe to run again.
cd /d "%~dp0"
set "ROOT=%CD%"

set "UV_EXE="
where uv >nul 2>nul
if not errorlevel 1 set "UV_EXE=uv"
if not defined UV_EXE if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"

if not defined UV_EXE (
    echo ***** Installing uv ^(Python package manager^)... *****
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
)

if not defined UV_EXE (
    echo ***** uv could not be installed. Install it from https://docs.astral.sh/uv/ and run this file again. *****
    pause
    exit /b 1
)

echo ***** Installing dependencies. The first run takes a few minutes... *****
"%UV_EXE%" sync --frozen
if errorlevel 1 (
    echo ***** Dependency installation failed. See the messages above. *****
    pause
    exit /b 1
)

echo ***** Creating the Desktop shortcut... *****
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\create_desktop_shortcut.ps1"
if errorlevel 1 (
    echo ***** The shortcut could not be created. See the messages above. *****
    pause
    exit /b 1
)

echo.
echo ***** Done. Double-click "MoneyPrinterTurbo" on your Desktop to start the app. *****
pause
