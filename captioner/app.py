#!/usr/bin/env python3
"""Local browser interface for Hinglish caption generation."""
import atexit
from pathlib import Path
import shutil
import tempfile
import uuid

import gradio as gr

from captioner_cli.local_workflow import (
    LANGUAGE_NAMES, MODEL_NAMES, generate_srt, transcribe_draft,
)


OUTPUT_ROOT = Path(tempfile.mkdtemp(prefix="hinglish-captions-"))
atexit.register(shutil.rmtree, OUTPUT_ROOT, ignore_errors=True)


def friendly_error(error):
    message = str(error)
    if "ffmpeg" in message.lower():
        return "FFmpeg could not read this file. Confirm FFmpeg is installed and try another media format."
    return message


def create_draft(media_path, model_name, language_label, context, device):
    try:
        transcript, detected_language = transcribe_draft(
            media_path,
            model_name=model_name,
            language=LANGUAGE_NAMES[language_label],
            context=context,
            device=device,
        )
        return transcript, detected_language, (
            f"Draft ready. Review every word, then generate the SRT. "
            f"Detected alignment language: `{detected_language}`."
        )
    except Exception as error:
        raise gr.Error(friendly_error(error)) from error


def create_srt_file(media_path, transcript, language, model_name, device):
    try:
        content, words = generate_srt(
            media_path, transcript, language, model_name=model_name, device=device)
        source_name = Path(media_path).stem if media_path else "captions"
        job_directory = OUTPUT_ROOT / uuid.uuid4().hex
        job_directory.mkdir()
        output_path = job_directory / f"{source_name}.words.srt"
        output_path.write_text(content, encoding="utf-8")
        review_count = sum(float(word["end"]) - float(word["start"]) > 1.5 for word in words)
        note = f"Generated {len(words)} aligned words."
        if review_count:
            note += f" Review {review_count} unusually long word timing(s) before publishing."
        return str(output_path), note
    except Exception as error:
        raise gr.Error(friendly_error(error)) from error


def build_app():
    with gr.Blocks(title="Hinglish Captions") as demo:
        gr.Markdown(
            "# Hinglish Captions\n"
            "Upload media, generate a local draft, correct the words, and download a word-level SRT. "
            "Your media stays on this computer."
        )
        with gr.Row():
            with gr.Column(scale=1):
                media = gr.File(
                    label="1. Upload audio or video",
                    file_types=["audio", "video"],
                    type="filepath",
                )
                model = gr.Dropdown(
                    choices=list(MODEL_NAMES), value="medium", label="Model",
                    info="Small is faster; large-v3 is most accurate and needs more memory.",
                )
                language_hint = gr.Dropdown(
                    choices=list(LANGUAGE_NAMES), value="Auto detect", label="Spoken language",
                )
                context = gr.Textbox(
                    label="Optional names and spellings",
                    placeholder="Sachin, DaVinci Resolve, SaaS...",
                    info="Hints only. Include unusual names or technical terms likely to be spoken.",
                )
                device = gr.Dropdown(
                    choices=["auto", "cpu", "cuda"], value="auto", label="Processing device",
                    info="Auto uses an NVIDIA GPU when available; otherwise CPU.",
                )
                draft_button = gr.Button("Generate draft transcript", variant="primary")
            with gr.Column(scale=2):
                transcript = gr.Textbox(
                    label="2. Review and correct the transcript",
                    lines=16,
                    placeholder="The generated transcript will appear here. Correct words only; do not summarize.",
                )
                alignment_language = gr.Textbox(
                    label="Alignment language code",
                    value="en",
                    info="Usually hi for Hindi-dominant speech or en for English-dominant speech.",
                )
                generate_button = gr.Button("Generate word-level SRT", variant="primary")
                output = gr.File(label="3. Download captions")
        status = gr.Markdown("First use downloads the selected model and can take several minutes.")

        draft_button.click(
            create_draft,
            inputs=[media, model, language_hint, context, device],
            outputs=[transcript, alignment_language, status],
            concurrency_limit=1,
        )
        generate_button.click(
            create_srt_file,
            inputs=[media, transcript, alignment_language, model, device],
            outputs=[output, status],
            concurrency_limit=1,
        )
    return demo


if __name__ == "__main__":
    build_app().queue(default_concurrency_limit=1, max_size=4).launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        share=False,
        allowed_paths=[str(OUTPUT_ROOT)],
        show_error=False,
    )
