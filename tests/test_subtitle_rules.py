import unittest

from core.subtitle_rules import MAX_BYTES, SubtitleError, subtitle_name, to_webvtt


class SubtitleRulesTests(unittest.TestCase):
    def test_matching_and_language(self):
        self.assertEqual(subtitle_name('фильм.mp4', 'фильм.ru.srt'), ('ru', 'Русский', '.srt'))
        self.assertEqual(subtitle_name('film.mp4', 'film.en-US.VTT'), ('en-US', 'English', '.vtt'))
        self.assertEqual(subtitle_name('film.mp4', 'film.srt'), ('und', 'Без языка', '.srt'))
        self.assertEqual(subtitle_name('film.mp4', 'film.fr.srt'), ('fr', 'fr', '.srt'))
        for name in ('film2.ru.srt', '../film.ru.srt', 'film.x.srt', 'film.ru.extra.srt', 'film.ru.txt'):
            with self.subTest(name=name):
                self.assertIsNone(subtitle_name('film.mp4', name))

    def test_srt_conversion_and_bom(self):
        source = '\ufeff1\r\n00:00:01,250 --> 00:00:03,500\r\nТекст, запятая\r\n'
        out = to_webvtt(source.encode('utf-8'), '.srt').decode('utf-8')
        self.assertEqual(out, 'WEBVTT\n\n1\n00:00:01.250 --> 00:00:03.500\nТекст, запятая\n')

    def test_cp1251_and_valid_webvtt(self):
        source = '1\n00:00:01,000 --> 00:00:02,000\nПривет\n'.encode('cp1251')
        self.assertIn('Привет', to_webvtt(source, '.srt').decode('utf8'))
        self.assertEqual(to_webvtt(b'\xef\xbb\xbfWEBVTT\r\n\r\nhello\r\n', '.vtt'), b'WEBVTT\n\nhello\n')
        with self.assertRaises(SubtitleError):
            to_webvtt(b'not-vtt', '.vtt')
        with self.assertRaises(SubtitleError):
            to_webvtt(b'\x98', '.srt')
        with self.assertRaises(SubtitleError):
            to_webvtt(b'x', '.txt')
        with self.assertRaises(SubtitleError):
            to_webvtt(b'x' * (MAX_BYTES + 1), '.srt')
