#!/usr/bin/env python3
"""Align corrected transcripts and export validated one-word captions."""
import argparse
import json
import math
from pathlib import Path
import re
import sys

if __package__:
    from .srt_generator import generate_one_word_srt, validate_word_segments
else:
    from srt_generator import generate_one_word_srt, validate_word_segments

TIMESTAMP = re.compile(r"^\[\s*([\d:.,]+)\s*-->\s*([\d:.,]+)\s*\]\s*(.*)$")


def convert_timestamp_to_seconds(value):
    parts = value.replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Invalid timestamp: {value}")
    numbers = [float(part) for part in parts]
    if any(not math.isfinite(n) or n < 0 for n in numbers) or any(n >= 60 for n in numbers[1:]):
        raise ValueError(f"Invalid timestamp: {value}")
    return sum(n * 60 ** i for i, n in enumerate(reversed(numbers)))


def validate_segments(segments, duration):
    previous_end = 0.0
    if not segments:
        raise ValueError("Transcript is empty.")
    for index, segment in enumerate(segments, 1):
        segment["text"] = " ".join(segment["text"].split())
        start, end = float(segment["start"]), float(segment["end"])
        if (not segment["text"] or not math.isfinite(start) or not math.isfinite(end)
                or start < previous_end or end <= start or end > duration):
            raise ValueError(f"Segment {index}: empty text, overlapping, or out-of-range timestamps "
                             f"({start}–{end}; audio duration {duration:.3f}s).")
        segment.update(start=start, end=end)
        previous_end = end
    return segments


def parse_json_transcript(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list) or not segments:
        raise ValueError("JSON must contain a nonempty segments list.")
    result = []
    for item in segments:
        if not isinstance(item, dict) or not {"text", "start", "end"} <= item.keys():
            raise ValueError("Every JSON segment needs text, start, and end.")
        result.append({key: item[key] for key in ("text", "start", "end")})
    return " ".join(s["text"] for s in result).split(), result


def parse_txt_transcript(path, total_duration):
    lines = [line.strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
             if line.strip()]
    segments, plain = [], []
    for index, line in enumerate(lines, 1):
        match = TIMESTAMP.fullmatch(line)
        if match:
            start, end, text = match.groups()
            segments.append(dict(text=text, start=convert_timestamp_to_seconds(start),
                                 end=convert_timestamp_to_seconds(end)))
        elif "-->" in line or line.startswith("["):
            raise ValueError(f"Malformed timestamp on line {index}.")
        else:
            plain.append(line)
    if segments and plain:
        raise ValueError("Use either plain text or timestamped lines, not a mixture.")
    if plain:
        segments = [dict(text=" ".join(plain), start=0.0, end=total_duration)]
    validate_segments(segments, total_duration)
    return " ".join(s["text"] for s in segments).split(), segments


def build_segment_words(source_words, aligned_words, segment_start, segment_end):
    """Use acoustic timings only when every source word is accounted for."""
    actual = [w.get("word", "").strip() for w in aligned_words]
    if actual != source_words:
        raise ValueError(f"Alignment changed/missed words in {segment_start:.3f}–{segment_end:.3f}s. "
                         "Check the transcript and split this passage at a speech pause.")
    result = []
    for source, aligned in zip(source_words, aligned_words):
        if aligned.get("start") is None or aligned.get("end") is None:
            raise ValueError(f"No acoustic timestamp for {source!r} in "
                             f"{segment_start:.3f}–{segment_end:.3f}s. "
                             "Try spelling numbers as spoken words or correcting the transcript.")
        start, end = float(aligned["start"]), float(aligned["end"])
        if start < segment_start or end > segment_end:
            raise ValueError(f"Word {source!r} is outside its source segment.")
        result.append(dict(aligned, word=source, start=start, end=end))
    validate_word_segments(result)
    return result


def align_whisperx(whisperx, audio, segments, language, device):
    model, metadata = whisperx.load_align_model(language_code=language, device=device)
    words = []
    # Sentence splitting means output segment indices are not input indices.
    for segment in segments:
        result = whisperx.align([segment], model, metadata, audio, device,
                                return_char_alignments=False)
        words.extend(build_segment_words(segment["text"].split(), result["word_segments"],
                                         segment["start"], segment["end"]))
    return words


def run_whisperx(args):
    import whisperx

    audio = whisperx.load_audio(str(args.audio_path))
    duration = len(audio) / 16000.0
    if args.transcript_path:
        if args.transcript_path.suffix.lower() == ".json":
            _, segments = parse_json_transcript(args.transcript_path)
        else:
            _, segments = parse_txt_transcript(args.transcript_path, duration)
        language = args.language or "en"
    else:
        model = whisperx.load_model(args.model, args.device, compute_type=args.compute_type,
                                    language=args.language, vad_method="silero")
        result = model.transcribe(audio, batch_size=4)
        segments, language = result["segments"], result["language"]
        del model
    validate_segments(segments, duration)
    if any(s["end"] - s["start"] > 30 for s in segments):
        print("Warning: long WhisperX windows can drift. Use short timestamped passages "
              "or try --engine stable-ts for plain text.", file=sys.stderr)
    return align_whisperx(whisperx, audio, segments, language, args.device)


def merge_token_words(source_words, words):
    """Merge tokenizer pieces only when they reconstruct an exact source word."""
    merged, cursor = [], 0
    for source in source_words:
        pieces, assembled = [], ""
        while cursor < len(words) and assembled != source:
            piece = words[cursor]
            assembled += piece["word"].strip()
            pieces.append(piece)
            cursor += 1
            if not source.startswith(assembled):
                raise ValueError(f"Aligner changed the transcript near {source!r}.")
        if assembled != source or not pieces:
            raise ValueError(f"Aligner omitted {source!r}.")
        # A tokenizer fragment can have zero duration even when the complete
        # word has valid timing. Validate fragments without treating them as cues.
        previous_end = 0.0
        for piece in pieces:
            if piece.get("start") is None or piece.get("end") is None:
                raise ValueError(f"Missing fragment timestamp in word {source!r}.")
            start, end = float(piece["start"]), float(piece["end"])
            if (not math.isfinite(start) or not math.isfinite(end)
                    or start < previous_end or end < start):
                raise ValueError(f"Invalid fragment timing in word {source!r}: {start}–{end}s.")
            previous_end = end
        merged.append(dict(word=source, start=pieces[0]["start"], end=pieces[-1]["end"]))
    if cursor != len(words):
        raise ValueError("Aligner returned extra words.")
    validate_word_segments(merged)
    return merged


def run_stable_ts(args):
    if not args.transcript_path or args.transcript_path.suffix.lower() != ".txt":
        raise ValueError("stable-ts requires a corrected plain .txt transcript.")
    if not args.language:
        raise ValueError("Specify --language for stable-ts (for example en or hi).")
    text = args.transcript_path.read_text(encoding="utf-8-sig").strip()
    if not text or "-->" in text:
        raise ValueError("stable-ts requires nonempty plain text without timestamps.")
    import stable_whisper

    model = stable_whisper.load_model(args.model, device=args.device)
    result = model.align(str(args.audio_path), " ".join(text.split()), language=args.language,
                         vad=True, suppress_silence=True, suppress_word_ts=True,
                         regroup=False, remove_instant_words=False)
    if result is None:
        raise ValueError("Alignment failed; check that the transcript matches the audio.")
    words = [word for segment in result.to_dict()["segments"] for word in segment["words"]]
    return merge_token_words(text.split(), words)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("transcript_path", type=Path, nargs="?")
    parser.add_argument("--engine", choices=["whisperx", "stable-ts"], default="whisperx")
    parser.add_argument("--model", default="large-v3", help="Whisper transcription/stable-ts model")
    parser.add_argument("--language", help="Language code (en, hi); auto-detect for transcription")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--compute-type", "--compute_type", choices=["float32", "int8"], default="float32")
    parser.add_argument("--output", type=Path, help="Default: AUDIO.words.srt")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    try:
        for path in (args.audio_path, args.transcript_path):
            if path is not None and not path.is_file():
                raise ValueError(f"File does not exist: {path}")
        output = args.output or args.audio_path.with_suffix(".words.srt")
        if output.resolve() in {p.resolve() for p in (args.audio_path, args.transcript_path) if p}:
            raise ValueError("Output must not overwrite an input file.")
        if output.exists() and not args.overwrite:
            raise ValueError(f"Output already exists: {output}. Use --overwrite to replace it.")
        words = run_stable_ts(args) if args.engine == "stable-ts" else run_whisperx(args)
        content = generate_one_word_srt(words)
        for index, word in enumerate(words, 1):
            if word["end"] - word["start"] > 1.5:
                print(f"Review word {index} {word['word']!r} at {word['start']:.3f}s: "
                      "duration exceeds 1.5s.", file=sys.stderr)
        with output.open("w" if args.overwrite else "x", encoding="utf-8") as handle:
            handle.write(content)
        cue_count = content.count("\n\n") + 1
        print(f"Saved {cue_count} captions ({len(words)} words) to {output}")
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, ImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
