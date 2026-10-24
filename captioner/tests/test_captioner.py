import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from captioner_cli.srt_generator import format_srt_time, generate_one_word_srt
from captioner_cli.local_workflow import (
    generate_srt, normalize_transcript, resolve_device, transcribe_draft,
)
from captioner_cli.transcribe import (
    align_whisperx, align_with_stable_model, build_segment_words, main, merge_token_words,
    parse_arguments, parse_json_transcript, parse_txt_transcript, run_stable_ts,
    run_whisperx, validate_segments,
)


def word(text, start, end):
    return dict(word=text, start=start, end=end)


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def transcript(self, text):
        path = self.root / "corrected.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_plain_lines_form_one_sequential_transcript(self):
        words, segments = parse_txt_transcript(self.transcript("aaj hum\nstartup banayenge"), 20)
        self.assertEqual(words, ["aaj", "hum", "startup", "banayenge"])
        self.assertEqual(segments, [dict(text="aaj hum startup banayenge", start=0, end=20)])

    def test_timestamp_formats_and_silence(self):
        _, segments = parse_txt_transcript(self.transcript(
            "[00:01,250 --> 00:02.500] hello\n[00:00:09.000 --> 00:00:10.000] again"), 12)
        self.assertEqual(segments[0]["start"], 1.25)
        self.assertEqual(segments[1]["start"], 9)

    def test_invalid_transcripts_fail(self):
        for text in ("", "[bad --> 1] hello", "[00:01 --> 00:02] hi\nplain",
                     "[00:02 --> 00:01] hi", "[00:00 --> 00:21] hi",
                     "[00:00 --> 00:02] hi\n[00:01 --> 00:03] again",
                     "[00:99 --> 02:00] hi"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_txt_transcript(self.transcript(text), 20)

    def test_json_requires_explicit_times(self):
        with self.assertRaises(ValueError):
            parse_json_transcript(self.transcript('{"segments":[{"text":"hi"}]}'))

    def test_segment_rejects_nonfinite_time(self):
        with self.assertRaises(ValueError):
            validate_segments([dict(text="hi", start=0, end=float("nan"))], 20)

    def test_preserve_long_pause(self):
        words = [word("hello", 1, 1.4), word("again", 12, 12.5)]
        self.assertEqual(build_segment_words(["hello", "again"], words, 0, 15), words)
        srt = generate_one_word_srt(words)
        self.assertIn("00:00:01,000 --> 00:00:01,400", srt)
        self.assertIn("00:00:12,000 --> 00:00:12,500", srt)

    def test_missing_word_does_not_redistribute_whole_segment(self):
        with self.assertRaises(ValueError):
            build_segment_words(["hello", "79", "again"],
                                [word("hello", 1, 2), {"word": "79"}, word("again", 9, 10)], 0, 12)

    def test_same_count_wrong_words_rejected(self):
        with self.assertRaises(ValueError):
            build_segment_words(["hello"], [word("wrong", 1, 2)], 0, 12)

    def test_outside_anchor_rejected(self):
        with self.assertRaises(ValueError):
            build_segment_words(["hello"], [word("hello", 1, 4)], 0, 3)

    def test_sentence_splitting_does_not_shift_following_segment(self):
        engine = Mock()
        engine.load_align_model.return_value = ("model", {})
        first = [word("Hello.", 1, 2), word("Again.", 4, 5)]
        second = [word("Next.", 10, 11)]
        engine.align.side_effect = [
            dict(segments=[dict(words=first[:1]), dict(words=first[1:])], word_segments=first),
            dict(segments=[dict(words=second)], word_segments=second),
        ]
        result = align_whisperx(engine, [], [dict(text="Hello. Again.", start=0, end=6),
                                            dict(text="Next.", start=9, end=12)], "en", "cpu")
        self.assertEqual(result, first + second)

    def test_srt_rejects_invalid_times(self):
        for start, end in ((None, 1), (0, None), (1, 1), (2, 1), (-1, 1),
                           (0, float("nan")), (0, float("inf")), (1, 1.0001)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                generate_one_word_srt([word("hi", start, end)])

    def test_overlapping_cues_rejected(self):
        with self.assertRaises(ValueError):
            generate_one_word_srt([word("hi", 0, 2), word("there", 1, 3)])

    def test_empty_or_multiword_cues_rejected(self):
        for words in ([], [word("", 0, 1)], [word("hi there", 0, 1)]):
            with self.assertRaises(ValueError):
                generate_one_word_srt(words)

    def test_time_rounding_carries_to_next_hour(self):
        self.assertEqual(format_srt_time(3599.9996), "01:00:00,000")

    def test_token_pieces_reconstruct_roman_hindi(self):
        self.assertEqual(merge_token_words(["banayenge"],
                         [word(" ban", 1, 1.2), word("ayenge", 1.2, 1.8)]),
                         [word("banayenge", 1, 1.8)])

    def test_token_mismatch_or_missing_timing_rejected(self):
        for words in ([word("wrong", 0, 1)], [], [word("hi", None, 1)],
                      [word("hi", 0, 1), word("extra", 1, 2)]):
            with self.assertRaises(ValueError):
                merge_token_words(["hi"], words)

    def test_zero_duration_fragments_merge_into_valid_word(self):
        self.assertEqual(merge_token_words(["aaj"],
                         [word("a", 1, 1), word("aj", 1, 1.4)]),
                         [word("aaj", 1, 1.4)])
        self.assertEqual(merge_token_words(["aaj"],
                         [word("aa", 1, 1.4), word("j", 1.4, 1.4)]),
                         [word("aaj", 1, 1.4)])

    def test_zero_duration_word_survives_token_merging(self):
        self.assertEqual(merge_token_words(["aaj"], [word("a", 1, 1), word("aj", 1, 1)]),
                         [word("aaj", 1, 1)])

    def test_zero_duration_word_merges_into_next_caption(self):
        self.assertEqual(generate_one_word_srt([word("a", 3.2, 3.2), word("Visa", 3.2, 3.6)]),
                         "1\n00:00:03,200 --> 00:00:03,600\na Visa\n")

    def test_consecutive_zero_words_keep_order_and_next_timing(self):
        words = [word("It's", 2, 3), word("a", 3.2, 3.2), word("Visa", 3.2, 3.2),
                 word("card", 4, 4.5), word("number", 4.5, 5)]
        self.assertEqual(generate_one_word_srt(words),
                         "1\n00:00:02,000 --> 00:00:03,000\nIt's\n\n"
                         "2\n00:00:04,000 --> 00:00:04,500\na Visa card\n\n"
                         "3\n00:00:04,500 --> 00:00:05,000\nnumber\n")
        self.assertEqual(words[1], word("a", 3.2, 3.2))

    def test_trailing_zero_word_has_no_next_caption(self):
        with self.assertRaisesRegex(ValueError, "no next caption"):
            generate_one_word_srt([word("Visa", 1, 2), word("a", 2, 2)])

    def test_zero_word_carries_across_whisperx_segment_boundary(self):
        first = build_segment_words(["a"], [word("a", 1, 1)], 0, 2)
        second = build_segment_words(["Visa"], [word("Visa", 3, 4)], 2, 5)
        self.assertEqual(generate_one_word_srt(first + second),
                         "1\n00:00:03,000 --> 00:00:04,000\na Visa\n")

    def test_bad_fragment_times_still_rejected(self):
        for start, end in ((1.2, 1.1), (float("nan"), 1.5), (1, float("inf")), (-1, 0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                merge_token_words(["aaj"], [word("a", start, end), word("aj", 2, 3)])

    def test_merged_words_must_not_overlap(self):
        with self.assertRaises(ValueError):
            merge_token_words(["aaj", "hum"], [word("aaj", 1, 2), word("hum", 1.5, 3)])

    def test_automatic_path_uses_transcription_segments(self):
        engine = Mock()
        engine.load_audio.return_value = [0] * 16000
        engine.load_model.return_value.transcribe.return_value = dict(
            segments=[dict(text="hi", start=0, end=1)], language="en")
        args = parse_arguments(["test.mp3"])
        with patch.dict("sys.modules", whisperx=engine), patch(
                "captioner_cli.transcribe.align_whisperx", return_value=[word("hi", 0, 1)]) as align:
            self.assertEqual(run_whisperx(args), [word("hi", 0, 1)])
            self.assertEqual(align.call_args.args[2], [dict(text="hi", start=0, end=1)])

    def test_optional_backend_enables_silence_detection(self):
        engine = Mock()
        engine.load_model.return_value.align.return_value.to_dict.return_value = dict(
            segments=[dict(words=[word("aaj", 2, 3)])])
        args = parse_arguments(["test.mp3", str(self.transcript("aaj")), "--language", "hi"])
        with patch.dict("sys.modules", stable_whisper=engine):
            self.assertEqual(run_stable_ts(args), [word("aaj", 2, 3)])
        self.assertTrue(engine.load_model.return_value.align.call_args.kwargs["vad"])

    def test_stable_model_alignment_normalizes_text(self):
        model = Mock()
        model.align.return_value.to_dict.return_value = dict(
            segments=[dict(words=[word("aaj", 1, 2), word("hum", 2, 3)])])
        self.assertEqual(
            align_with_stable_model(model, "audio.mp3", " aaj\n hum ", "hi"),
            [word("aaj", 1, 2), word("hum", 2, 3)],
        )
        self.assertEqual(model.align.call_args.args, ("audio.mp3", "aaj hum"))
        self.assertEqual(model.align.call_args.kwargs["language"], "hi")

    def test_local_draft_transcription(self):
        media = self.root / "reel.mp4"
        media.touch()
        model = Mock()
        model.transcribe.return_value.to_dict.return_value = dict(
            segments=[dict(text=" Aaj hum"), dict(text="build karenge.")], language="hi")
        with patch("captioner_cli.local_workflow.get_stable_model", return_value=model):
            transcript, language = transcribe_draft(media, language="hi", context="SaaS")
        self.assertEqual(transcript, "Aaj hum build karenge.")
        self.assertEqual(language, "hi")
        options = model.transcribe.call_args.kwargs
        self.assertEqual(options["language"], "hi")
        self.assertIn("SaaS", options["initial_prompt"])
        self.assertTrue(options["vad"])

    def test_local_srt_generation_uses_corrected_transcript(self):
        media = self.root / "reel.mp4"
        media.touch()
        model = Mock()
        model.align.return_value.to_dict.return_value = dict(
            segments=[dict(words=[word("aaj", 1, 2), word("hum", 2, 3)])])
        with patch("captioner_cli.local_workflow.get_stable_model", return_value=model):
            content, words = generate_srt(media, "aaj hum", "hi")
        self.assertEqual(words, [word("aaj", 1, 2), word("hum", 2, 3)])
        self.assertIn("aaj", content)
        self.assertIn("hum", content)

    def test_local_workflow_validates_inputs(self):
        with self.assertRaises(ValueError):
            normalize_transcript(" \n ")
        self.assertEqual(resolve_device("cpu"), "cpu")
        with self.assertRaises(ValueError):
            transcribe_draft(self.root / "missing.mp3")
        media = self.root / "reel.mp3"
        media.touch()
        with self.assertRaises(ValueError):
            generate_srt(media, "", "hi")

    def test_failed_alignment_preserves_existing_output(self):
        audio = self.root / "test.mp3"
        audio.touch()
        output = audio.with_suffix(".words.srt")
        output.write_text("original", encoding="utf-8")
        with patch("captioner_cli.transcribe.run_whisperx", return_value=[word("hi", 1, None)]), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(audio), "--overwrite"]), 1)
        self.assertEqual(output.read_text(), "original")

    def test_cli_writes_one_word_file(self):
        audio = self.root / "test.mp3"
        audio.touch()
        with patch("captioner_cli.transcribe.run_whisperx", return_value=[word("hi", 1, 2)]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(audio)]), 0)
        self.assertEqual(audio.with_suffix(".words.srt").read_text(),
                         "1\n00:00:01,000 --> 00:00:02,000\nhi\n")

    def test_input_and_existing_output_protected_before_model_load(self):
        audio = self.root / "test.mp3"
        audio.touch()
        audio.with_suffix(".words.srt").touch()
        with patch("captioner_cli.transcribe.run_whisperx") as engine, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(audio)]), 1)
            self.assertEqual(main([str(audio), "--output", str(audio), "--overwrite"]), 1)
        engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
