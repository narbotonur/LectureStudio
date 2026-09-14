@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "lecture_studio_entry.py" %*
) else (
    python "lecture_studio_entry.py" %*
)
if errorlevel 1 (
    echo Lecture Studio could not start. See README.md for setup instructions.
    pause
    exit /b 1
)
