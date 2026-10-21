# Hinglish Captions

Generate word-level SRT captions by aligning a reviewed Roman Hinglish transcript to audio or video.

The command-line tool, installation instructions, usage examples, limitations, and test instructions are in [captioner/README.md](captioner/README.md).

## Repository contents

- `captioner/captioner_cli/`: caption alignment and SRT generation code
- `captioner/tests/`: unit tests
- `captioner/requirements.txt`: core WhisperX dependency
- `captioner/requirements-alignment.txt`: optional experimental alignment backend

Local virtual environments, model weights, media files, secrets, caches, and generated word-level captions are intentionally excluded from Git.
