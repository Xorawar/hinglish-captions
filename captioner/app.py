#!/usr/bin/env python3
"""Local, sequential interface for preparing word-level captions."""
import atexit
from html import escape
from pathlib import Path
import shutil
import tempfile
import uuid

import gradio as gr
from captioner_cli.local_workflow import generate_srt, normalize_transcript
from captioner_cli.draft_jobs import cancel_draft, stream_draft

OUTPUT_ROOT = Path(tempfile.mkdtemp(prefix="hinglish-captions-"))
atexit.register(shutil.rmtree, OUTPUT_ROOT, ignore_errors=True)
LANGUAGES = {"Hinglish / Hindi": "hi", "English": "en"}
CSS_PATH = Path(__file__).with_name("ui.css")


def build_theme():
    """Keep native controls consistent with the light canvas in either OS theme."""
    colors = {
        "body_background_fill": "#f4f3ef",
        "body_text_color": "#202823",
        "body_text_color_subdued": "#647068",
        "background_fill_primary": "#ffffff",
        "background_fill_secondary": "#f4f6f1",
        "block_background_fill": "#ffffff",
        "block_border_color": "#dde2dc",
        "block_label_background_fill": "#ffffff",
        "block_label_text_color": "#3e4b42",
        "block_info_text_color": "#647068",
        "border_color_primary": "#dde2dc",
        "table_odd_background_fill": "#f8faf7",
        "table_even_background_fill": "#ffffff",
        "table_text_color": "#202823",
        "link_text_color": "#176b56",
        "link_text_color_hover": "#11513f",
        "link_text_color_visited": "#176b56",
        "input_background_fill": "#ffffff",
        "input_background_fill_focus": "#ffffff",
        "input_background_fill_hover": "#f8faf7",
        "input_border_color": "#d5ddd4",
        "input_border_color_focus": "#176b56",
        "input_border_color_hover": "#a7b9ac",
        "input_placeholder_color": "#69756d",
        "button_primary_background_fill": "#176b56",
        "button_primary_background_fill_hover": "#11513f",
        "button_primary_border_color": "#176b56",
        "button_primary_text_color": "#ffffff",
        "button_primary_text_color_hover": "#ffffff",
        "button_secondary_background_fill": "#ffffff",
        "button_secondary_background_fill_hover": "#f3f6f0",
        "button_secondary_border_color": "#d5ddd4",
        "button_secondary_text_color": "#344239",
        "button_secondary_text_color_hover": "#202823",
    }
    return gr.themes.Base(
        primary_hue="emerald", secondary_hue="emerald", neutral_hue="gray",
        font=["-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        font_mono=["ui-monospace", "Consolas", "monospace"],
    ).set(**colors, **{f"{key}_dark": value for key, value in colors.items()},
          block_radius="10px", input_radius="8px", button_large_radius="10px",
          button_large_text_size="14px", block_label_text_size="12px")


def friendly_error(error):
    if "ffmpeg" in str(error).lower():
        return "We couldn't read this media. Check FFmpeg is installed or try another file."
    return str(error)


def stepper(active):
    items = []
    for index, label in enumerate(("Media", "Transcript", "Create", "Download")):
        state = "active" if index == active else "done" if index < active else ""
        current = ' aria-current="step"' if index == active else ""
        items.append(f'<li class="{state}"{current}><span>{index + 1}</span>{label}</li>')
    return '<ol class="steps" aria-label="Caption progress">' + "".join(items) + "</ol>"


def page_updates(active):
    return [gr.update(visible=index == active) for index in range(4)] + [stepper(active)]


def next_page(media_path):
    if not media_path or not Path(media_path).is_file():
        raise gr.Error("Add an audio or video file to continue.")
    return page_updates(1)


def read_transcript(path):
    try:
        if not path or Path(path).suffix.lower() != ".txt":
            raise ValueError("Choose a plain .txt transcript.")
        with Path(path).open("rb") as source:
            content = source.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError("Choose a text file smaller than 1 MB.")
        text = content.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Choose a plain UTF-8 text file.")
        normalize_transcript(text)
        return text, gr.update(value="Transcript imported. Review the words, then create your captions.", visible=True)
    except UnicodeDecodeError as error:
        raise gr.Error("Save your transcript as UTF-8 text, then upload it again.") from error
    except (ValueError, OSError) as error:
        raise gr.Error(friendly_error(error)) from error


def import_transcript(path):
    text, _ = read_transcript(path)
    return gr.update(value=text, visible=True), gr.update(visible=True)


def clear_imported_transcript():
    return gr.update(value="", visible=False), gr.update(visible=False)


def processing_card(draft=False, current=None, total=None, stage=None):
    title = "Listening to your media" if draft else "Putting every word in place"
    description = "Creating a draft for you to review." if draft else "Matching your transcript to the audio and building your SRT."
    if total and current is not None:
        percent = min(100, max(0, current / total * 100))
        progress = f'<progress max="100" value="{percent:.1f}" aria-label="Audio transcribed"></progress><p>{percent:.0f}% · {current:.0f} of {total:.0f} seconds transcribed</p>'
    else:
        progress = '<div class="progress-track" aria-hidden="true"><span></span></div>'
    return f'''<div class="processing" role="status" aria-live="polite">
        <div class="wave" aria-hidden="true">{"<i></i>" * 9}</div>
        <p class="eyebrow">WORKING ON YOUR COMPUTER</p><h2>{title}</h2>
        <p>{escape(stage or description)}</p>{progress}
        <p class="muted">This may take a few minutes. First use also downloads the model.<br>Keep this window open.</p></div>'''


def run_job(media_path, transcript, model, language, draft=False, session=None):
    """Stream screen transitions and preserve the editor on failure."""
    try:
        if not media_path or not Path(media_path).is_file():
            raise ValueError("Your media is no longer available. Go back and add it again.")
        language_code = LANGUAGES[language]
        if not draft:
            normalize_transcript(transcript)
    except (ValueError, KeyError) as error:
        gr.Warning(friendly_error(error))
        yield (*page_updates(1), gr.skip(), gr.skip(), gr.skip(), gr.skip())
        return
    yield (*page_updates(2), processing_card(draft), gr.skip(), None, "")
    try:
        if draft:
            for kind, payload in stream_draft(session or uuid.uuid4().hex, media_path, model, language_code):
                if kind == "error":
                    raise RuntimeError(payload)
                if kind == "result":
                    gr.Info("Draft ready. Review every word before creating captions.")
                    yield (*page_updates(1), gr.skip(), gr.update(value=payload, visible=True), None, "")
                else:
                    card = (processing_card(True, *payload) if kind == "progress"
                            else processing_card(True, stage=payload))
                    yield (*page_updates(2), card, gr.skip(), None, "")
            return
        content, words = generate_srt(media_path, transcript, language_code, model_name=model)
        job_directory = OUTPUT_ROOT / uuid.uuid4().hex
        job_directory.mkdir()
        filename = f"{Path(media_path).stem}.words.srt"
        output_path = job_directory / filename
        output_path.write_text(content, encoding="utf-8")
        review_count = sum(float(word["end"]) - float(word["start"]) > 1.5 for word in words)
        note = (f"Review {review_count} unusually long word timing(s) in your editor."
                if review_count else "Ready to bring into your video editor.")
        card = f'''<div class="result-card"><div class="file-icon" aria-hidden="true">SRT</div>
            <p class="eyebrow">YOUR CAPTIONS ARE READY</p><h2>Give your words the spotlight.</h2>
            <p class="filename">{escape(filename)}</p><div class="file-meta"><span>{len(words)} words aligned</span>
            <span>Word-level SRT</span></div><p class="muted">{note}</p></div>'''
        yield (*page_updates(3), gr.skip(), gr.skip(), str(output_path), card)
    except Exception as error:
        gr.Warning("Couldn't finish. " + friendly_error(error) +
                   " Your transcript is still here; you can edit it and try again.")
        yield (*page_updates(1), gr.skip(), gr.skip(), None, "")


def build_app():
    with gr.Blocks(title="Hinglish Captions", analytics_enabled=False) as demo:
        gr.HTML('<header class="brand"><span class="brand-icon" aria-hidden="true">hc</span>'
                '<span>hinglish captions</span><span class="local-badge">Local & private</span></header>')
        navigation = gr.HTML(stepper(0))
        with gr.Column(elem_id="wizard"):
            with gr.Column(elem_classes="screen") as media_page:
                gr.HTML('<p class="eyebrow">01 / START WITH YOUR STORY</p><h1>Good words.<br>Great captions.</h1>'
                        '<p class="intro">Turn your audio or video into word-level captions, ready for your next reel.</p>')
                media = gr.File(label="Add your audio or video", file_types=["audio", "video"],
                                type="filepath", elem_id="media-drop")
                with gr.Row():
                    model = gr.Dropdown(choices=[("Small · faster", "small"), ("Medium · balanced", "medium"),
                                                ("Large · more detail", "large-v3")], value="medium", label="Model")
                    language = gr.Dropdown(choices=list(LANGUAGES), value="Hinglish / Hindi", label="Spoken language")
                gr.Markdown("Bigger models need more memory and time. Add your transcript in the next step.", elem_classes="helper")
                next_button = gr.Button("Continue to transcript →", variant="primary")
            with gr.Column(visible=False, elem_classes="screen") as transcript_page:
                gr.HTML('<p class="eyebrow">02 / YOUR WORDS, YOUR WAY</p><h1>Get the words right.</h1>'
                        '<p class="intro">Paste the exact spoken words, including repetitions. Don’t translate or summarize.</p>')
                with gr.Tabs(elem_id="transcript-options", overflow_behavior="wrap"):
                    with gr.Tab("★ Recommended · Type or paste", id="manual"):
                        gr.HTML('<div class="option-reason"><strong>Best when you already know the exact words.</strong>'
                                '<p>Paste or type your reviewed Roman Hinglish transcript for the most accurate captions.</p></div>')
                        manual_transcript = gr.Textbox(
                            label="Your transcript", lines=10, elem_id="manual-transcript-editor",
                            placeholder="Aaj hum baat karenge…\n\nType or paste your reviewed transcript here.")
                        manual_generate = gr.Button("Create my captions →", variant="primary",
                                                    elem_classes="action-button")
                    with gr.Tab("★ Recommended · Upload .txt", id="upload"):
                        gr.HTML('<div class="option-reason"><strong>Best for a transcript prepared elsewhere.</strong>'
                                '<p>Upload a reviewed UTF-8 .txt file. You can edit its contents before creating captions.</p></div>')
                        upload = gr.File(label="Choose a .txt file", file_types=[".txt"], type="filepath",
                                         elem_id="transcript-file")
                        upload_transcript = gr.Textbox(
                            label="Your uploaded transcript", lines=10, visible=False,
                            elem_id="upload-transcript-editor")
                        upload_generate = gr.Button("Create my captions →", variant="primary", visible=False,
                                                    elem_classes="action-button")
                    with gr.Tab("Optional · Generate with Whisper", id="whisper"):
                        gr.HTML('<div class="option-reason warning"><strong>Use this only when you don’t have a transcript.</strong>'
                                '<p>Whisper takes a few minutes and may miss words, spell Hinglish poorly, or use Hindi script. Review the result carefully.</p></div>')
                        draft_button = gr.Button("✦ Generate a draft with Whisper", variant="secondary",
                                                 elem_classes="action-button secondary-action")
                        whisper_transcript = gr.Textbox(
                            label="Whisper draft — review every word", lines=10, visible=False,
                            elem_id="whisper-transcript-editor")
                        whisper_generate = gr.Button("Create my captions →", variant="primary", visible=False,
                                                     elem_classes="action-button")
                back_button = gr.Button("← Back to media", variant="secondary",
                                        elem_classes="navigation-button")
            with gr.Column(visible=False, elem_classes="screen") as processing_page:
                processing = gr.HTML(processing_card())
                cancel_button = gr.Button("Cancel draft & return to transcript", variant="secondary",
                                          visible=False, elem_classes="cancel-button")
            with gr.Column(visible=False, elem_classes="screen") as result_page:
                result = gr.HTML()
                download = gr.DownloadButton("↓ Download .srt", variant="primary")
                edit_button = gr.Button("← Edit transcript", variant="secondary", elem_classes="navigation-button")
                restart_button = gr.Button("Caption another file", variant="secondary", elem_classes="navigation-button")
        gr.HTML('<footer><span class="creator-credit">Made with <span class="footer-heart" aria-label="love">♥</span> by '
                '<a href="https://www.instagram.com/egpg.builds/" target="_blank" '
                'rel="noopener noreferrer">egpg.builds</a></span>'
                '<span>Files stay on your computer.</span></footer>')
        pages = [media_page, transcript_page, processing_page, result_page, navigation]
        next_button.click(next_page, media, pages, show_progress="hidden")
        back_button.click(lambda: page_updates(0), outputs=pages, show_progress="hidden")
        edit_button.click(lambda: page_updates(1), outputs=pages, show_progress="hidden")
        upload.upload(import_transcript, upload, [upload_transcript, upload_generate],
                      show_progress="hidden")
        upload.clear(clear_imported_transcript, outputs=[upload_transcript, upload_generate],
                     show_progress="hidden")

        def caption_outputs(transcript):
            return pages + [processing, transcript, download, result]

        for button, transcript in [
            (manual_generate, manual_transcript),
            (upload_generate, upload_transcript),
            (whisper_generate, whisper_transcript),
        ]:
            button.click(run_job, [media, transcript, model, language],
                         caption_outputs(transcript), show_progress="hidden",
                         concurrency_limit=1, concurrency_id="caption-model")

        def draft_job(media_path, text, model_name, language_name, request: gr.Request):
            try:
                for update in run_job(media_path, text, model_name, language_name,
                                      draft=True, session=request.session_hash):
                    on_processing_page = update[2].get("visible", False)
                    transcript_update = update[6]
                    has_draft = (isinstance(transcript_update, dict)
                                 and transcript_update.get("visible", False)
                                 and "value" in transcript_update)
                    on_transcript_page = update[1].get("visible", False)
                    yield (*update,
                           gr.update(visible=on_processing_page),
                           gr.update(visible=on_transcript_page and has_draft),
                           gr.update(visible=on_transcript_page and not has_draft))
            finally:
                cancel_draft(request.session_hash)

        whisper_outputs = caption_outputs(whisper_transcript)
        draft_event = draft_button.click(draft_job, [media, whisper_transcript, model, language],
                                        whisper_outputs + [cancel_button, whisper_generate, draft_button],
                                        show_progress="hidden", concurrency_limit=1,
                                        concurrency_id="caption-model")

        def cancel_job(request: gr.Request):
            cancel_draft(request.session_hash)
            gr.Info("Draft cancelled. Choose a recommended option or start Whisper again.")
            return (*page_updates(1), gr.update(visible=False),
                    gr.update(visible=True), gr.update(visible=False), gr.update(visible=False))

        cancel_button.click(cancel_job, outputs=pages + [cancel_button, draft_button,
                                                         whisper_generate, whisper_transcript],
                            cancels=[draft_event], queue=False, show_progress="hidden")
        restart_button.click(
            lambda: (*page_updates(0), None, "", "", "", None, "", None),
            outputs=pages + [media, manual_transcript, upload_transcript, whisper_transcript,
                             download, result, upload],
            show_progress="hidden")
    return demo


if __name__ == "__main__":
    build_app().queue(default_concurrency_limit=1, max_size=4).launch(
        server_name="127.0.0.1", inbrowser=True, share=False,
        allowed_paths=[str(OUTPUT_ROOT)], show_error=False,
        theme=build_theme(),
        css_paths=[CSS_PATH], footer_links=[],
    )
