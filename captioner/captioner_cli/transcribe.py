#!/usr/bin/env python3
import os
import sys
import argparse
import warnings
import json
import re
from typing import List, Dict, Any, Tuple

# Suppress underlying library performance/deprecation noise
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import whisperx
import torch

from srt_generator import generate_one_word_srt

def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))

def build_segment_words(
    source_words: List[str],
    aligned_words: List[Dict[str, Any]],
    segment_start: float,
    segment_end: float,
) -> List[Dict[str, Any]]:
    """
    Maps words inside one TXT segment only.

    No generated word can begin before segment_start or end after
    segment_end.
    """
    result: List[Dict[str, Any]] = []
    word_count = len(source_words)

    if word_count == 0:
        return result

    valid_aligned = [
        word
        for word in aligned_words
        if word.get("start") is not None and word.get("end") is not None
    ]

    # Use acoustic timings only when WhisperX returned exactly the same
    # number of words for this segment.
    if len(valid_aligned) == word_count:
        previous_end = segment_start

        for source_word, aligned_word in zip(source_words, valid_aligned):
            start = clamp(
                float(aligned_word["start"]),
                segment_start,
                segment_end,
            )
            end = clamp(
                float(aligned_word["end"]),
                start,
                segment_end,
            )

            start = max(start, previous_end)

            if end <= start:
                end = min(segment_end, start + 0.001)

            result.append({
                "word": source_word,
                "start": start,
                "end": end,
            })

            previous_end = end

        # The final word can never exceed the TXT segment.
        result[-1]["end"] = min(result[-1]["end"], segment_end)
        return result

    # WhisperX dropped or added words.
    # Distribute the original words inside the exact TXT segment instead
    # of extending beyond it.
    segment_duration = max(0.001, segment_end - segment_start)

    weights = [max(1, len(re.sub(r"[^\w]", "", word))) for word in source_words]
    total_weight = sum(weights)

    cursor = segment_start

    for index, (source_word, weight) in enumerate(zip(source_words, weights)):
        if index == word_count - 1:
            end = segment_end
        else:
            duration = segment_duration * (weight / total_weight)
            end = min(segment_end, cursor + duration)

        result.append({
            "word": source_word,
            "start": cursor,
            "end": end,
        })

        cursor = end

    result[-1]["end"] = segment_end
    return result

def parse_arguments() -> argparse.Namespace:
    """
    Sets up application parameters using standard argparse layout.
    """
    parser = argparse.ArgumentParser(
        description="Production-grade Local Audio Transcription & Forced Alignment Tool"
    )
    parser.add_argument(
        "audio_path",
        type=str,
        help="Path to local target audio/video media asset (e.g. wave, mp3, mp4)"
    )
    parser.add_argument(
        "transcript_path",
        type=str,
        nargs="?",
        default=None,
        help="Optional: Path to manual text transcript (.txt), timestamped text (.txt), or Whisper (.json)."
    )
    parser.add_argument(
        "--compute_type",
        type=str,
        default="float32",
        choices=["float32", "int8"],
        help="Precision type to use. macOS CPU defaults smoothly to float32."
    )
    return parser.parse_args()

def check_file_exists(file_path: str) -> None:
    """
    Ensures that essential files are accessible before loading expensive AI models.
    """
    if not os.path.isfile(file_path):
        print(f"Error: Target path validation failed: '{file_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

def run_transcription_pipeline(audio_path: str, compute_type: str) -> List[Dict[str, Any]]:
    """
    Executes standard WhisperX pipeline path: Audio -> Transcription -> Language Detection -> Alignment.
    """
    device = "cpu"
    print(f"[*] Initializing WhisperX Base Model tracking [Device: {device} | Precision: {compute_type}]...")
    
    model = whisperx.load_model("base", device, compute_type=compute_type)
    
    print("[*] Processing audio sample arrays...")
    audio = whisperx.load_audio(audio_path)
    
    print("[*] Running machine transcription inference...")
    raw_result = model.transcribe(audio, batch_size=16)
    
    detected_language = raw_result.get("language", "en")
    print(f"[*] Language successfully discovered: '{detected_language}'")
    
    print(f"[*] Instantiating alignment engine for language: '{detected_language}'...")
    align_model, align_metadata = whisperx.load_align_model(language_code=detected_language, device=device)
    
    print("[*] Commencing fine-grained word alignment execution...")
    aligned_result = whisperx.align(
        text_segments,
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    aligned_segments = aligned_result.get("segments", [])
    final_segments: List[Dict[str, Any]] = []

    for index, source_segment in enumerate(text_segments):
        segment_start = float(source_segment["start"])
        segment_end = float(source_segment["end"])
        source_words = source_segment["text"].split()

        aligned_words: List[Dict[str, Any]] = []

        if index < len(aligned_segments):
            aligned_words = aligned_segments[index].get("words", [])

        segment_words = build_segment_words(
            source_words=source_words,
            aligned_words=aligned_words,
            segment_start=segment_start,
            segment_end=segment_end,
        )

        final_segments.extend(segment_words)

    return final_segments

def convert_timestamp_to_seconds(ts_str: str) -> float:
    """
    Converts timestamp strings like '01:23.456' or '00:01:23.456' into total float seconds.
    """
    parts = ts_str.strip().split(':')
    if len(parts) == 2:
        # Format: MM:SS.mmm
        minutes = float(parts[0])
        seconds = float(parts[1])
        return (minutes * 60.0) + seconds
    elif len(parts) == 3:
        # Format: HH:MM:SS.mmm
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return (hours * 3600.0) + (minutes * 60.0) + seconds
    else:
        return float(ts_str)

def parse_json_transcript(json_path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Parses a modified Whisper JSON file to extract linear word tokens and anchor segments.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    segments_list = data.get("segments", []) if isinstance(data, dict) else data
    if not segments_list:
        print("Error: Provided JSON file does not contain a valid 'segments' block.", file=sys.stderr)
        sys.exit(1)
        
    source_words: List[str] = []
    text_segments: List[Dict[str, Any]] = []
    
    for seg in segments_list:
        text = seg.get("text", "").strip()
        if not text:
            continue
            
        source_words.extend(text.split())
        text_segments.append({
            "text": text,
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0))
        })
        
    return source_words, text_segments

def parse_txt_transcript(txt_path: str, total_duration: float) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Parses a plain or timestamp-prefixed .txt file to build text segment blocks.
    Supports: [MM:SS.mmm --> MM:SS.mmm] Plain text token strings
    """
    with open(txt_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()
        
    source_words: List[str] = []
    text_segments: List[Dict[str, Any]] = []
    
    # Matches patterns like: [01:23.450 --> 01:25.100] or [00:01:23.450 --> 00:01:25.100]
    timestamp_pattern = re.compile(r'^\[\s*([\d:.]+)\s*-->\s*([\d:.]+)\s*\](.*)$')
    
    for line_num, line in enumerate(raw_lines, 1):
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
            
        match = timestamp_pattern.match(cleaned_line)
        if match:
            # Case A: Line contains explicit micro-timestamps
            start_str, end_str, text_str = match.groups()
            text_content = text_str.strip()
            if not text_content:
                continue
                
            try:
                start_secs = convert_timestamp_to_seconds(start_str)
                end_secs = convert_timestamp_to_seconds(end_str)
            except Exception as e:
                print(f"Warning: Line {line_num} has malformed timestamps. Defaulting to full bounds.", file=sys.stderr)
                start_secs = 0.0
                end_secs = total_duration
                
            source_words.extend(text_content.split())
            text_segments.append({
                "text": text_content,
                "start": start_secs,
                "end": end_secs
            })
        else:
            # Case B: Line is a plain un-timestamped string text row
            source_words.extend(cleaned_line.split())
            text_segments.append({
                "text": cleaned_line,
                "start": 0.0,
                "end": total_duration
            })
            
    return source_words, text_segments

def run_forced_alignment_pipeline(audio_path: str, transcript_path: str, compute_type: str) -> List[Dict[str, Any]]:
    """
    Executes an unconstrained acoustic forced alignment pipeline. Parses input data 
    dynamically (JSON, plain TXT, or timestamped TXT) and restitches word parameters.
    """
    device = "cpu"
    print("[*] Loading target audio arrays...")
    audio = whisperx.load_audio(audio_path)
    total_audio_seconds = float(len(audio)) / 16000.0
    
    _, ext = os.path.splitext(transcript_path.lower())
    
    if ext == ".json":
        print(f"[*] Parsing manual Whisper JSON from: {transcript_path}")
        source_words, text_segments = parse_json_transcript(transcript_path)
    else:
        print(f"[*] Parsing manual Text / Timestamped-Text script from: {transcript_path}")
        source_words, text_segments = parse_txt_transcript(transcript_path, total_audio_seconds)
        
    if not source_words:
        print("Error: Target transcript structural text tokens array is empty.", file=sys.stderr)
        sys.exit(1)
        
    print(f"[*] Tokenized Script Verification. Loaded {len(source_words)} exact literal words.")
    print("[*] Loading unconstrained acoustic alignment models...")
    
    # "en" provides maximum acoustic resolution tracking via Wav2Vec2 without timeline drift
    align_model, align_metadata = whisperx.load_align_model(language_code="en", device=device)
    
    print("[*] Processing global acoustic map matrices with anchor segments...")
    aligned_result = whisperx.align(
        text_segments,
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
    )

    print("Audio duration:", total_audio_seconds)

    words = aligned_result["word_segments"]

    print("Last 10 aligned words:")

    for w in words[-10:]:
        print(w)

    print("Last aligned end:", words[-1]["end"])

    aligned_segments = aligned_result.get("segments", [])
    final_segments: List[Dict[str, Any]] = []

    for index, source_segment in enumerate(text_segments):
        segment_start = float(source_segment["start"])
        segment_end = float(source_segment["end"])
        source_words = source_segment["text"].split()

        aligned_words: List[Dict[str, Any]] = []

        if index < len(aligned_segments):
            aligned_words = aligned_segments[index].get("words", [])

        segment_words = build_segment_words(
            source_words=source_words,
            aligned_words=aligned_words,
            segment_start=segment_start,
            segment_end=segment_end,
        )

        final_segments.extend(segment_words)

    return final_segments

def main() -> None:
    args = parse_arguments()
    
    check_file_exists(args.audio_path)
    base_name, _ = os.path.splitext(args.audio_path)
    output_srt_path = f"{base_name}.srt"
    try:
        if args.transcript_path is not None:
            check_file_exists(args.transcript_path)
            word_segments = run_forced_alignment_pipeline(audio_path=args.audio_path,transcript_path=args.transcript_path,compute_type=args.compute_type)
        else:
            word_segments = run_transcription_pipeline(audio_path=args.audio_path,compute_type=args.compute_type)
            
        print("[*] Generating one-word-per-frame sequential SRT matrix payload...")
        srt_content = generate_one_word_srt(word_segments)
        print(f"[*] Writing finalized subtitle file out onto disk: {output_srt_path}")
        
        with open(output_srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_content)
            print(f"[+] Task completed smoothly! Final SRT built at: {output_srt_path}")
    
    except Exception as err:
        print(f"\n[-] Execution Critical Pipeline Failure Encountered: {err}", file=sys.stderr)
        sys.exit(1)
        
if __name__ == "__main__":
    main()
    
