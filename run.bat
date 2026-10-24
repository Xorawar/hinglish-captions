@echo off
setlocal

cd /d "%~dp0"
set "ENV_VERSION=1"
set "INSTALLED_VERSION="

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo FFmpeg is required. Install it with: winget install Gyan.FFmpeg
    exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if (3, 10) ^<= sys.version_info[:2] ^<= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Python 3.10-3.12 is required. Python 3.11 is recommended.
    echo Download it from https://www.python.org/downloads/ and run this file again.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local Python environment...
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
)

if exist ".venv\.hinglish-captions-env" set /p INSTALLED_VERSION=<".venv\.hinglish-captions-env"
if not "%INSTALLED_VERSION%"=="%ENV_VERSION%" (
    echo Installing dependencies ^(first launch can take several minutes^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    ".venv\Scripts\python.exe" -m pip install -r "captioner\requirements-ui.txt"
    if errorlevel 1 exit /b 1
    >".venv\.hinglish-captions-env" echo %ENV_VERSION%
)

echo Starting Hinglish Captions at http://127.0.0.1:7860
".venv\Scripts\python.exe" "captioner\app.py"
