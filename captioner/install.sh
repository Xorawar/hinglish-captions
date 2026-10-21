#!/usr/bin/env zsh

set -eu
cd -- "${0:A:h}"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Install FFmpeg first (macOS: brew install ffmpeg)." >&2
    exit 1
fi

# A fresh environment avoids mutating the legacy environment tracked in Git.
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel setuptools
.venv/bin/python -m pip install -r requirements.txt
echo "Installed. From the captioner directory run:"
echo 'source .venv/bin/activate'
echo 'python captioner_cli/transcribe.py AUDIO TRANSCRIPT'
