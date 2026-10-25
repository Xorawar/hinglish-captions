"""Annotation parsing, acoustic text preservation, and per-cue SRT formatting."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from captioner_cli.annotations import apply_annotations, parse_annotations
from captioner_cli.local_workflow import generate_srt
from captioner_cli.srt_generator import generate_one_word_srt
from captioner_cli.transcribe import align_whisperx, align_with_stable_model


def aligned(*tokens):
    return [dict(word=token, start=index, end=index + 1) for index, token in enumerate(tokens)]


class AnnotationTests(unittest.TestCase):
    def export(self, text, **colors):
        plain, annotations = parse_annotations(text)
        return generate_one_word_srt(apply_annotations(aligned(*plain.split()), annotations), **colors)

    def test_plain_transcript_remains_byte_identical_including_numbers(self):
        for text in ("Aaj 25% off hai.", "5 < 10 & 10 > 5", "aaj\n hum"):
            with self.subTest(text=text):
                plain, annotations = parse_annotations(text)
                self.assertEqual(plain, text)
                self.assertIsNone(annotations)
                self.assertEqual(self.export(text), generate_one_word_srt(aligned(*text.split())))

    def test_nested_phrase_closes_styles_in_every_cue(self):
        result = self.export('Ye <b><i><highlight>bahut zaroori</highlight></i></b> hai.')
        self.assertIn('<b><i><font color="#FFD600">bahut</font></i></b>\n', result)
        self.assertIn('<b><i><font color="#FFD600">zaroori</font></i></b>\n', result)
        self.assertIn('<font color="#FFFFFF">Ye</font>', result)
        self.assertNotIn("<highlight>", result)

    def test_whitespace_and_punctuation_preserved_in_parser(self):
        plain, annotations = parse_annotations('  <b>wow</b>!\n\t<i>haan & ji</i>  ')
        self.assertEqual(plain, '  wow!\n\thaan & ji  ')
        self.assertEqual(annotations[0], [("wow", ("b",)), ("!", ())])
        result = self.export('<b>wow</b>!')
        self.assertIn('<b><font color="#FFFFFF">wow</font></b><font color="#FFFFFF">!</font>', result)

    def test_annotations_inside_token_do_not_change_alignment_word_count(self):
        plain, annotations = parse_annotations('ban<b>ayenge</b>')
        self.assertEqual(plain, "banayenge")
        self.assertEqual(len(annotations), 1)

    def test_malformed_and_unsupported_tags_fail(self):
        for text in ('<b>wow', '</i>wow', '<b><i>wow</b></i>', '<strong>wow</strong>',
                     '<b class="x">wow</b>', '<highlight/>', '<b></b>', '<b><b>wow</b></b>',
                     '<B>wow</B>', '<b', '<script>alert(1)</script>', '<!-- comment -->',
                     '<b>  </b>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_annotations(text)

    def test_numbers_highlighted_only_in_annotated_mode(self):
        result = self.export('<b>Sirf</b> ₹1,500 25% 10kg GPT-4 26/10/2026', highlight_color="#00FF00")
        for token in ("₹1,500", "25%", "10kg", "GPT-4", "26/10/2026"):
            self.assertIn(f'<font color="#00FF00">{token}</font>', result)
        self.assertIn('<b><font color="#FFFFFF">Sirf</font></b>', result)

    def test_explicit_highlight_and_numeric_highlight_do_not_nest(self):
        result = self.export('<highlight>25%</highlight>')
        self.assertEqual(result.count('<font'), 1)

    def test_protected_tokens_and_literal_characters(self):
        result = self.export('<b>Visit</b> https://example.com/25 a2@example.com &')
        self.assertNotIn('#FFD600', result)
        self.assertIn('&amp;', result)

    def test_custom_colors_and_invalid_colors(self):
        result = self.export('<b>Aaj</b> <highlight>hum</highlight>',
                             subtitle_color="#123456", highlight_color="#abcdef")
        self.assertIn('<font color="#123456">Aaj</font>', result)
        self.assertIn('<font color="#abcdef">hum</font>', result)
        for color in ('red', '#fff', '#FFFFFG', '#FFFFFF" onclick="bad', None):
            with self.subTest(color=color), self.assertRaises(ValueError):
                self.export('<b>hello</b>', highlight_color=color)

    def test_zero_duration_carry_keeps_both_word_styles(self):
        _, annotations = parse_annotations('<b>a</b> <i>Visa</i>')
        words = aligned('a', 'Visa')
        words[0].update(start=1, end=1)
        result = generate_one_word_srt(apply_annotations(words, annotations))
        self.assertEqual(result, '1\n00:00:01,000 --> 00:00:02,000\n'
                         '<b><font color="#FFFFFF">a</font></b> '
                         '<i><font color="#FFFFFF">Visa</font></i>\n')

    def test_mapping_rejects_wrong_words_and_does_not_mutate_input(self):
        _, annotations = parse_annotations('<b>hi</b>')
        words = aligned('hi')
        apply_annotations(words, annotations)
        self.assertNotIn('annotations', words[0])
        for invalid in (aligned('bye'), aligned('hi', 'extra'), []):
            with self.assertRaises(ValueError):
                apply_annotations(invalid, annotations)

    def test_stable_alignment_receives_plain_text(self):
        model = Mock()
        model.align.return_value.to_dict.return_value = dict(segments=[dict(words=aligned('aaj', 'hum'))])
        words = align_with_stable_model(model, 'audio.mp3', '<b>aaj\n hum</b>', 'hi')
        self.assertEqual(model.align.call_args.args, ('audio.mp3', 'aaj hum'))
        self.assertEqual([item['word'] for item in words], ['aaj', 'hum'])
        self.assertEqual(generate_one_word_srt(words).count('<b>'), 2)

    def test_whisperx_receives_plain_text_and_preserves_source(self):
        engine = Mock()
        engine.load_align_model.return_value = ('model', {})
        engine.align.return_value = dict(word_segments=aligned('hi', 'there'))
        segments = [dict(text='<i>hi there</i>', start=0, end=2)]
        words = align_whisperx(engine, [], segments, 'en', 'cpu')
        self.assertEqual(engine.align.call_args.args[0][0]['text'], 'hi there')
        self.assertEqual(segments[0]['text'], '<i>hi there</i>')
        self.assertEqual(generate_one_word_srt(words).count('<i>'), 2)

    def test_local_workflow_validates_before_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / 'clip.wav'
            media.touch()
            with patch('captioner_cli.local_workflow.get_stable_model') as load:
                for text in ('<b>hi', '<b> </b>', '<font>hi</font>'):
                    with self.subTest(text=text), self.assertRaises(ValueError):
                        generate_srt(media, text, 'hi')
                load.assert_not_called()

    def test_local_workflow_exports_annotations_with_custom_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / 'clip.wav'
            media.touch()
            model = Mock()
            model.align.return_value.to_dict.return_value = dict(segments=[dict(words=aligned('hi', '25'))])
            with patch('captioner_cli.local_workflow.get_stable_model', return_value=model):
                result, words = generate_srt(media, '<b>hi</b> 25', 'hi', highlight_color='#123456')
            self.assertIn('<b><font color="#FFFFFF">hi</font></b>', result)
            self.assertIn('<font color="#123456">25</font>', result)
            self.assertEqual([item['word'] for item in words], ['hi', '25'])
