import datetime
from typing import Dict, List, Any

def format_srt_time(seconds: float) -> str:
    """
    Converts a float duration in seconds to standard SRT timestamp format: HH:MM:SS,mmm
    """
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    milliseconds = int(round((seconds - total_seconds) * 1000))
    
    # Handle overflow bounds safely
    if milliseconds >= 1000:
        secs += 1
        milliseconds -= 1000
    if secs >= 60:
        minutes += 1
        secs -= 60
    if minutes >= 60:
        hours += 1
        minutes -= 60
        
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def generate_one_word_srt(word_segments: List[Dict[str, Any]]) -> str:
    """
    Takes aligned words from WhisperX and formats them into a single-word-per-frame SRT string.
    Ensures safe fallbacks for missing alignment intervals.
    """
    srt_lines: List[str] = []
    counter = 1
    
    print("test################")

    # Track the last known valid end time to fill gaps if WhisperX drops word boundaries
    last_valid_time = 0.0

    for idx, word_data in enumerate(word_segments):
        # Extract word token
        word = word_data.get("word", "").strip()
        if not word:
            continue
            
        # Get start/end boundaries safely with continuous fallbacks
        start_time = word_data.get("start")
        end_time = word_data.get("end")
        
        if start_time is None:
            start_time = last_valid_time
            
        if end_time <= start_time:
            end_time = start_time + 0.1
            
        # Ensure times always advance strictly monotonically
        if start_time is None or end_time is None:
            raise ValueError(
                f"Missing timestamp for word {idx + 1}: {word!r}"
            )

        start_time = float(start_time)
        end_time = float(end_time)

        if end_time < start_time:
            end_time = start_time
            
        # Format strings into SRT block layout
        start_str = format_srt_time(start_time)
        end_str = format_srt_time(end_time)
        
        srt_lines.append(str(counter))
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(word)
        srt_lines.append("") # Blank trailing separation newline
        
        counter += 1
        last_valid_time = end_time

    return "\n".join(srt_lines)

