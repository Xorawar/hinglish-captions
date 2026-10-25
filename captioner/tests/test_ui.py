"""Wizard regression tests (requires requirements-ui.txt)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import gradio
except ImportError:
    gradio = None
else:
    import app


@unittest.skipIf(gradio is None, "UI dependencies are not installed")
class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "clip.wav"
        self.media.touch()

    def test_import_preserves_text_and_accepts_bom(self):
        source = Path(self.temp.name) / "transcript.txt"
        source.write_text("Aaj hum\nbaat karenge.", encoding="utf-8-sig")
        self.assertEqual(app.read_transcript(source)[0], "Aaj hum\nbaat karenge.")
        for content in (b"", b"\xff", b"hello\x00world", b"x" * 1_000_001):
            source.write_bytes(content)
            with self.assertRaises(gradio.Error):
                app.read_transcript(source)

    def test_import_reveals_editor_and_generate_button(self):
        source = Path(self.temp.name) / "transcript.txt"
        source.write_text("Reviewed words", encoding="utf-8")
        editor, button = app.import_transcript(source)
        self.assertEqual(editor["value"], "Reviewed words")
        self.assertTrue(editor["visible"])
        self.assertTrue(button["visible"])
        cleared_editor, cleared_button = app.clear_imported_transcript()
        self.assertEqual(cleared_editor["value"], "")
        self.assertFalse(cleared_editor["visible"])
        self.assertFalse(cleared_button["visible"])

    def test_manual_transcript_skips_transcription_and_creates_download(self):
        with patch.object(app, "stream_draft") as draft, patch.object(
            app, "generate_srt", return_value=("1\n00:00:00,000 --> 00:00:00,500\nAaj\n",
                                               [{"start": 0, "end": .5}])
        ) as align:
            states = list(app.run_job(str(self.media), "Aaj", "small", "Hinglish / Hindi"))
        draft.assert_not_called()
        align.assert_called_once_with(str(self.media), "Aaj", "hi", model_name="small",
                                      subtitle_color="#FFFFFF", highlight_color="#FFD600")
        self.assertTrue(states[0][2]["visible"])
        self.assertTrue(states[-1][3]["visible"])
        self.assertIn("Aaj", Path(states[-1][7]).read_text())

    def test_failure_returns_to_editor_and_preserves_transcript(self):
        with patch.object(app, "generate_srt", side_effect=ValueError("No alignment")), \
                patch.object(app.gr, "Warning") as warning:
            states = list(app.run_job(str(self.media), "Aaj", "small", "English"))
        self.assertTrue(states[-1][1]["visible"])
        self.assertEqual(states[-1][6], gradio.skip())
        self.assertIsNone(states[-1][7])
        self.assertIn("No alignment", warning.call_args.args[0])

    def test_annotated_transcript_and_colors_reach_export(self):
        source = Path(self.temp.name) / "transcript.txt"
        source.write_text('<b>Aaj</b> <highlight>hum</highlight>', encoding="utf-8")
        text = app.read_transcript(source)[0]
        with patch.object(app, "generate_srt", return_value=("captions", [])) as generate:
            states = list(app.run_job(str(self.media), text, "small", "English",
                                      "#123456", "#abcdef"))
        generate.assert_called_once_with(str(self.media), text, "en", model_name="small",
                                         subtitle_color="#123456", highlight_color="#abcdef")
        self.assertTrue(states[-1][3]["visible"])

    def test_optional_draft_returns_to_review_without_exporting(self):
        with patch.object(app, "stream_draft", return_value=iter([("progress", (5, 10)), ("result", "Aaj hum")])), patch.object(app, "generate_srt") as align:
            states = list(app.run_job(str(self.media), "", "small", "Hinglish / Hindi", draft=True))
        align.assert_not_called()
        self.assertTrue(states[-1][1]["visible"])
        self.assertEqual(states[-1][6]["value"], "Aaj hum")
        self.assertTrue(states[-1][6]["visible"])
        self.assertIn('value="50.0"', states[1][5])
        self.assertIn("5 of 10 seconds", states[1][5])

    def test_cancelled_stream_does_not_overwrite_editor(self):
        with patch.object(app, "stream_draft", return_value=iter([])):
            states = list(app.run_job(str(self.media), "My existing words", "small", "English", draft=True))
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0][6], gradio.skip())

    def test_empty_transcript_never_starts_model(self):
        with patch.object(app, "generate_srt") as align:
            states = list(app.run_job(str(self.media), "   ", "small", "English"))
        align.assert_not_called()
        self.assertEqual(len(states), 1)
        self.assertTrue(states[0][1]["visible"])

    def test_result_filename_is_html_escaped(self):
        media = Path(self.temp.name) / "<img src=x>.wav"
        media.touch()
        with patch.object(app, "generate_srt", return_value=("captions", [])):
            states = list(app.run_job(str(media), "hello", "small", "English"))
        self.assertIn("&lt;img src=x&gt;", states[-1][8])
        self.assertNotIn("<img", states[-1][8])
