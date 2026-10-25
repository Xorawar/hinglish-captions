"""Reusable local transcription and alignment workflow for the browser UI."""
import gc
from pathlib import Path
import threading

from .srt_generator import generate_one_word_srt
from .annotations import parse_annotations, validate_colors
from .transcribe import align_with_stable_model


MODEL_NAMES = ("small", "medium", "large-v3")
LANGUAGE_NAMES = {"Auto detect": None, "Hinglish / Hindi": "hi", "English": "en"}
ROMAN_HINGLISH_PROMPT = (
    "Aaj hum Roman Hinglish mein baat karenge. Hindi aur English words Latin script mein."
)

_model = None
_model_key = None
_model_lock = threading.RLock()


def normalize_transcript(text):
    normalized = " ".join((text or "").split())
    if not normalized:
        raise ValueError("Generate or enter a transcript first.")
    return normalized


def resolve_device(requested):
    if requested != "auto":
        return requested
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def get_stable_model(model_name, device="auto"):
    """Load one faster-whisper model and reuse it for transcription and alignment."""
    global _model, _model_key
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unsupported model: {model_name}")
    resolved_device = resolve_device(device)
    compute_type = "float16" if resolved_device == "cuda" else "int8"
    key = (model_name, resolved_device, compute_type)
    with _model_lock:
        if _model_key != key:
            import stable_whisper
            _model = None
            _model_key = None
            gc.collect()
            _model = stable_whisper.load_faster_whisper(
                model_name, device=resolved_device, compute_type=compute_type)
            _model_key = key
        return _model


def transcribe_draft(media_path, model_name="medium", language=None, context="", device="auto",
                     progress_callback=None):
    path = Path(media_path) if media_path else None
    if path is None or not path.is_file():
        raise ValueError("Upload an audio or video file first.")
    model = get_stable_model(model_name, device)
    options = {"vad": True, "regroup": True}
    if progress_callback is not None:
        options["progress_callback"] = progress_callback
    if language:
        options["language"] = language
    context = " ".join((context or "").split())
    options["initial_prompt"] = " ".join(filter(None, (ROMAN_HINGLISH_PROMPT, context)))
    with _model_lock:
        result = model.transcribe(str(path), **options)
    data = result.to_dict()
    transcript = normalize_transcript(" ".join(
        segment.get("text", "") for segment in data.get("segments", [])))
    detected_language = data.get("language") or getattr(result, "language", None) or language or "en"
    return transcript, detected_language


def generate_srt(media_path, transcript, language, model_name="medium", device="auto",
                 subtitle_color="#FFFFFF", highlight_color="#FFD600"):
    path = Path(media_path) if media_path else None
    if path is None or not path.is_file():
        raise ValueError("The uploaded media is no longer available. Upload it again.")
    normalized = normalize_transcript(transcript)
    parse_annotations(normalized)
    validate_colors(subtitle_color, highlight_color)
    language = (language or "").strip().lower()
    if not language:
        raise ValueError("Enter an alignment language such as hi or en.")
    model = get_stable_model(model_name, device)
    with _model_lock:
        words = align_with_stable_model(model, path, normalized, language)
    return generate_one_word_srt(words, subtitle_color, highlight_color), words
