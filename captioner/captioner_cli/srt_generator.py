"""Word subtitles with zero-duration words carried into the next timed cue."""
import math


def milliseconds(seconds):
    value = float(seconds)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid timestamp: {seconds!r}")
    return round(value * 1000)


def format_srt_time(seconds):
    hours, remainder = divmod(milliseconds(seconds), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def validate_word_segments(word_segments):
    previous_end = 0
    for index, item in enumerate(word_segments, 1):
        word = item.get("word", "").strip()
        if len(word.split()) != 1:
            raise ValueError(f"Cue {index} must contain exactly one word: {word!r}")
        if item.get("start") is None or item.get("end") is None:
            raise ValueError(f"Missing timestamp for word {index}: {word!r}")
        raw_start, raw_end = float(item["start"]), float(item["end"])
        start, end = milliseconds(raw_start), milliseconds(raw_end)
        if raw_end < raw_start:
            raise ValueError(f"Reversed timestamps for word {index}: {word!r}")
        if raw_start != raw_end and end <= start:
            raise ValueError(f"Word {index} {word!r} has no positive duration at SRT precision "
                             f"({item['start']}–{item['end']}s). Check the transcript or try another alignment language.")
        if start < previous_end:
            raise ValueError(f"Word {index} {word!r} starts at {item['start']}s before "
                             f"the previous word ends at {previous_end / 1000}s.")
        previous_end = end
    if not word_segments:
        raise ValueError("No aligned words; no subtitle file was generated.")


def generate_one_word_srt(word_segments):
    validate_word_segments(word_segments)
    blocks, pending = [], []
    for item in word_segments:
        pending.append(item["word"].strip())
        if float(item["start"]) == float(item["end"]):
            continue
        blocks.append(f"{len(blocks) + 1}\n{format_srt_time(item['start'])} --> "
                      f"{format_srt_time(item['end'])}\n{' '.join(pending)}\n")
        pending = []
    if pending:
        raise ValueError(f"Zero-duration words at the end have no next caption: {' '.join(pending)!r}")
    return "\n".join(blocks)
