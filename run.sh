#!/bin/sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$PROJECT_DIR/.venv"
ENV_VERSION="1"
ENV_MARKER="$VENV_DIR/.hinglish-captions-env"

find_python() {
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
            'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' \
            >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ]; then
    echo "Python 3.10-3.12 is required. Python 3.11 is recommended." >&2
    echo "Download it from https://www.python.org/downloads/ and run this script again." >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg is required." >&2
    echo "macOS: brew install ffmpeg" >&2
    echo "Ubuntu/Debian: sudo apt install ffmpeg" >&2
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating the local Python environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

INSTALLED_VERSION=""
if [ -f "$ENV_MARKER" ]; then
    INSTALLED_VERSION=$(sed -n '1p' "$ENV_MARKER")
fi

if [ "$INSTALLED_VERSION" != "$ENV_VERSION" ]; then
    echo "Installing dependencies (first launch can take several minutes)..."
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/captioner/requirements-ui.txt"
    printf '%s\n' "$ENV_VERSION" > "$ENV_MARKER"
fi

echo "Starting Hinglish Captions on an available local port..."
exec "$VENV_DIR/bin/python" "$PROJECT_DIR/captioner/app.py"
