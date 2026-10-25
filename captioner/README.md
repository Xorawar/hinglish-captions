# Reel captions

Align an exact transcript to an audio/video file and normally export one whitespace word per SRT cue. Words with identical start and end times are prepended to the next timed cue, using that cue's unchanged timestamps (for example, `a Visa`). Consecutive zero-duration words carry forward together. Roman Hinglish spelling is preserved. Punctuation attached to a word stays attached.

## Local browser interface

Most users should start from the repository root and run `./run.sh` on macOS/Linux or `run.bat` on Windows. The local interface generates a draft transcript, lets the user correct it without creating a separate text file, and then exports the aligned SRT. See the [root README](../README.md) for prerequisites and quick-start instructions.

The browser interface uses the stable-ts Faster-Whisper integration for both draft transcription and corrected-text alignment, allowing it to reuse one downloaded model. Audio and video remain local, and the server listens only on `127.0.0.1`.

## Annotated transcripts

Paste or upload a transcript with optional `<b>`, `<i>`, and `<highlight>` tags:

```text
Ye <b>sirf <highlight>₹500</highlight></b> ka hai. Usne kaha, "<i>kal milte hain</i>".
```

Tags may be nested and may cover several words. The aligner receives only the spoken text; styles are reapplied to each word after exact matching. Every exported cue has balanced tags, including when zero-duration words carry into the next cue. Bold and italic export as `<b>` and `<i>`; highlight exports as `<font color="#FFD600">` by default.

Open **Annotated transcript styling** to choose the subtitle colour (default white, `#FFFFFF`) and highlight colour (default yellow, `#FFD600`). In annotated transcripts, tokens containing digits also receive the highlight colour, including currency, percentages, dates, and names such as `GPT-4`. URLs, email addresses, paths, and backtick-delimited code tokens are excluded from automatic highlighting. Written-out numbers and separate unit words are not automatically highlighted; annotate the full phrase when desired.

Plain transcripts retain the existing plain SRT output, including numbers; colour settings and automatic highlighting apply only when annotation tags are present. Unsupported tags, attributes, and malformed nesting produce an error instead of being passed to the aligner. Existing text entities are not decoded. The app does not call an AI service or rewrite the transcript.

Both CLI alignment engines support annotations. For timestamped TXT or JSON, close all tags within each segment. Set colours with `--subtitle-color '#FFFFFF' --highlight-color '#FFD600'` (six-digit hex values only).

To check an export manually, use a short clip with a nested annotation spanning several words, an unannotated number, and punctuation outside a tag. Import the SRT into DaVinci Resolve and check the colours, bold/italic combinations, and unchanged timing. Repeat with plain text to confirm the original appearance.

## What was causing drift

- One missing alignment discarded ALL acoustic timings in a segment. The fallback spread words by character length across the segment, including pauses.
- Each plain-text line was independently assigned the entire audio duration, causing overlapping alignment windows.
- WhisperX can split an input segment into multiple sentences. Pairing output and input segments by index assigned the wrong timings to later text.
- Automatic transcription referenced an undefined `text_segments` variable.
- SRT export compared missing end times before checking them, invented durations, and did not reject overlapping cues.
- Forced alignment always used an English acoustic model. Roman Hindi spelling does not make Hindi speech English; code switching remains an acoustic limitation even after the software bugs are fixed.
- Installation referenced a missing requirements file and generated a launcher pointing to an unrelated `~/captioner` directory.

The updated script preserves valid acoustic timing and pauses. If it cannot account for every word, it stops with an error instead of spreading words across silence. Strict checks can reject files that the old script would have exported with guessed timings. They do not prove that a plausible timestamp is acoustically correct.

## CLI setup

FFmpeg must be on PATH. Prefer a modern Python 3.11 installation for a fresh environment; the existing macOS system-Python 3.9 environment emits a LibreSSL compatibility warning. From this directory, use your working environment or create a fresh one:

```sh
zsh install.sh
source .venv/bin/activate
```

The installer installs WhisperX 3.7.5. It does not install a global command. Dependencies and models require downloads; transcription/alignment runs locally. Large-v3 on CPU may be slow and memory-intensive; `--model medium` trades potential accuracy for lower resource use. Transitive dependencies are not fully locked.

Virtual environments, downloaded model weights, local media, and generated word-level SRT files are excluded from Git. Recreate the environment from the requirements files rather than committing it.

## Corrected-text CLI workflow

1. Obtain an accurate Roman Hinglish transcript or generate and review one in the local browser interface. Save the exact spoken words in a plain UTF-8 `.txt` file. No timestamp reconstruction is needed for this route. Preserve repetitions and filler words; do not translate or rewrite sentences.
2. Install the optional alignment dependency in the active environment:

   ```sh
   python -m pip install -r requirements-alignment.txt
   ```

3. Align the corrected text:

   ```sh
   python captioner_cli/transcribe.py \
     ~/Downloads/Timeline\ 1.mp3 \
     ~/Downloads/Timeline\ 1.txt \
     --engine stable-ts --language hi --model large-v3
   ```

4. Import `Timeline 1.words.srt` into DaVinci Resolve, using the same timeline origin as the exported audio. Check the words immediately before and after pauses.

This optional backend uses Whisper-based alignment and Silero voice activity detection to adjust timing around non-speech. **It is experimental for your Roman Hinglish recordings, and stable-ts upstream development is paused.** It is not a guaranteed upgrade. See [upstream alignment documentation and maintenance notice](https://github.com/jianfch/stable-ts#alignment). `hi` is a starting point for Hindi-dominant speech; test `en` with a different `--output` if the Roman spelling aligns poorly. Neither setting guarantees code-switching accuracy. Background music can also confuse speech detection.

If this trial still drifts, a next candidate is aligning corrected Hindi in Devanagari with a Hindi acoustic model, then mapping timings to reviewed Roman captions. That requires explicit word correspondence; arbitrary transliteration or translation can change word counts. This mapping is not implemented here.

## Existing WhisperX route

Your original command still accepts timestamped TXT or Whisper JSON:

```sh
python captioner_cli/transcribe.py \
  ~/Downloads/Timeline\ 1.mp3 ~/Downloads/Timeline\ 1.txt
```

Timestamped TXT format:

```text
[00:00.500 --> 00:02.000] Aaj hum
[00:06.000 --> 00:08.500] startup banayenge.
```

Anchors must be ordered, non-overlapping, and within the audio. Keep each passage short and avoid enclosing long pauses. Malformed anchors or mixed plain/timestamped text fail explicitly. Plain multiline text is treated as one sequential passage, but whole-recording WhisperX alignment can drift; a warning is printed for windows longer than 30 seconds. WhisperX's language flag selects its acoustic model and should match the text's language/script. `--language hi` is not a Roman Hindi transliteration switch.

Without a transcript, the script now transcribes and aligns in one command:

```sh
python captioner_cli/transcribe.py ~/Downloads/Timeline\ 1.mp3 --model large-v3
```

Language is detected automatically for that route. This does not automatically produce corrected Roman Hinglish, and it may fail validation on unalignable words such as digits. For numeric captions, first try spelling numbers as actually spoken.

## Output and review

- Default output: `AUDIO.words.srt`, leaving Whisper's original `.srt` separate.
- Use `--output PATH` to compare attempts. Use `--overwrite` to explicitly replace existing output.
- Missing, nonfinite, negative, reversed, or overlapping timings are rejected before output is written. Exact zero-duration words merge into the next timed caption without extending its duration or filling a pause. Trailing zero-duration words cause an error because there is no next caption. Positive durations that round to zero milliseconds are rejected. Errors never trigger synthetic timing redistribution.
- Words longer than 1.5 seconds produce review warnings. This is a heuristic, not an accuracy/confidence score.
- Genuine pauses remain blank. Short gaps between spoken words are also preserved; there is no automatic caption hold or gap filling.
- `--compute-type int8` (legacy spelling `--compute_type`) applies to WhisperX transcription only. It does not accelerate the optional stable-ts backend.

The original audio export must include the same leading silence as the video timeline. Cutting silence or changing speed in only one source will invalidate timing, even with a good aligner.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests cover parsing, timestamp validation, pauses, dropped words, sentence splitting, tokenizer pieces, local draft generation, corrected-text alignment, automatic transcription wiring, and output protection. Backend calls are mocked; these tests do not measure model accuracy. No real audio/video sample is included in this repository.

Before relying on a backend, compare the same corrected transcript on three short clips: continuous speech, a 3–5 second pause, and repeated Hinglish words/numbers. Check the first and last word, both sides of every pause, and all review warnings in Resolve at your timeline frame rate. Keep the voice track and export timeline unchanged between runs.
