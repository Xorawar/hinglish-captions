# Hinglish Captions

Generate word-level SRT captions for Roman Hinglish audio and video. The tool runs locally: upload media, review the automatically generated transcript, and download captions from a browser interface.

No hosted service or API key is required. Media stays on your computer.

## Quick start

Install these prerequisites first:

- [Python 3.11](https://www.python.org/downloads/) (Python 3.10–3.12 is supported)
- [FFmpeg](https://ffmpeg.org/download.html)
- Git

### macOS or Linux

```sh
git clone https://github.com/Xorawar/hinglish-captions.git
cd hinglish-captions
./run.sh
```

On macOS with Homebrew, install the prerequisites with `brew install python@3.11 ffmpeg`.

### Windows

```powershell
git clone https://github.com/Xorawar/hinglish-captions.git
cd hinglish-captions
.\run.bat
```

Windows users can install the prerequisites with:

```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

The launcher installs the Python packages and opens <http://127.0.0.1:7860>. The first setup downloads several hundred MB of machine-learning packages. Generating the first transcript also downloads the selected speech model, which can range from hundreds of MB to a few GB. An internet connection and enough free disk space are required for those first downloads; later processing is local.

## How it works

1. Add audio or video, choose a model and the spoken language, and continue.
2. Paste your transcript or upload a UTF-8 `.txt` file. Optionally generate a draft, then review it in the editor.
3. Select **Create my captions**. A processing screen appears while the words are aligned.
4. Download your `.srt`, edit the transcript to try again, or start another file.

Automatic transcription is optional. For the best Roman Hinglish wording, provide your own reviewed transcript. Uploading a transcript or generating a draft replaces the text in the editor. Processing uses the available device automatically.

The transcript screen offers separate **Type or paste**, **Upload .txt**, and **Generate with Whisper** tabs. Whisper can take several minutes and may produce inaccurate wording. During generation, the UI shows model preparation followed by audio seconds processed and a percentage. **Cancel draft & return to transcript** stops the worker and preserves your existing text, so you can type or upload a transcript instead.

`medium` is the default model. Choose `small` on a lower-memory laptop or `large-v3` when accuracy matters more than speed and memory usage. Local transcription is not perfect; review the transcript before publishing.

## Privacy and generated files

The app binds only to `127.0.0.1` and does not create a public sharing link. Uploaded media is handled by the local Gradio process. Generated download files are stored in a temporary directory and removed when the app exits.

Virtual environments, model weights, media, secrets, caches, and generated word-level captions are excluded from Git.

## CLI and technical documentation

The existing command-line workflow, timing behavior, limitations, and test instructions are documented in [captioner/README.md](captioner/README.md).

## Tests

```sh
cd captioner
python -m unittest discover -s tests -v
```

## Creator

Created by Sachin Yadav — [@egpg.builds](https://www.instagram.com/egpg.builds/).

## License

Released under the [MIT License](LICENSE).
