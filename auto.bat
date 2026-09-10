@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0auto.py" %*
    exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0auto.py" %*
    exit /b
)
echo Python 3.12 or newer is required. Install Python, enable Add to PATH, and reopen this terminal.
exit /b 1
