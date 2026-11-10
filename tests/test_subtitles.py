import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.subtitle_rules import MAX_BYTES, SubtitleError
from storage import subtitles


class SubtitleStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.movie = self.root / 'video.mp4'
        self.movie.write_bytes(b'video')
        (self.root / 'video.ru.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nПривет\n', encoding='utf8')
        (self.root / 'video.en.vtt').write_text('WEBVTT\n\nEnglish\n', encoding='utf8')
        (self.root / 'other.ru.srt').write_text('ignored', encoding='utf8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_lookup_sort_and_read(self):
        tracks = subtitles.list_tracks(str(self.movie))
        self.assertEqual([x['lang'] for x in tracks], ['en', 'ru'])
        self.assertEqual(subtitles.read_track(str(self.movie), 0), b'WEBVTT\n\nEnglish\n')
        self.assertIn('00:00:01.000 --> 00:00:02.000', subtitles.read_track(str(self.movie), 1).decode('utf8'))
        for index in (-1, 2, True, 10**10):
            with self.subTest(index=index), self.assertRaises(SubtitleError):
                subtitles.read_track(str(self.movie), index)

    def test_oversized_file_is_not_listed(self):
        with (self.root / 'video.fr.srt').open('wb') as file:
            file.truncate(MAX_BYTES + 1)
        self.assertEqual([x['lang'] for x in subtitles.list_tracks(str(self.movie))], ['en', 'ru'])

    def test_hardlink_is_excluded(self):
        outside = self.root / 'private.txt'
        outside.write_text('secret')
        try:
            os.link(outside, self.root / 'video.fr.srt')
        except OSError as exc:
            self.skipTest(f'hard links unavailable: {exc}')
        self.assertEqual([x['lang'] for x in subtitles.list_tracks(str(self.movie))], ['en', 'ru'])

    def test_symlink_is_excluded(self):
        outside = self.root / 'private.txt'
        outside.write_text('secret')
        try:
            (self.root / 'video.fr.srt').symlink_to(outside)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        self.assertEqual([x['lang'] for x in subtitles.list_tracks(str(self.movie))], ['en', 'ru'])

    def test_replaced_file_is_checked_again_before_read(self):
        outside = self.root / 'private.txt'
        outside.write_text('secret')
        link = self.root / 'replacement'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        original = subtitles._tracks
        def replace_after_scan(media, directory_fd):
            result = original(media, directory_fd)
            os.replace(link, self.root / 'video.en.vtt')
            return result
        with patch.object(subtitles, '_tracks', side_effect=replace_after_scan):
            with self.assertRaises(SubtitleError):
                subtitles.read_track(str(self.movie), 0)

    def test_relative_path_and_limits_fail_closed(self):
        with self.assertRaises(SubtitleError):
            subtitles.list_tracks('video.mp4')
        with patch.object(subtitles, 'MAX_ENTRIES', 1):
            with self.assertRaises(SubtitleError):
                subtitles.list_tracks(str(self.movie))
        with patch.object(subtitles, 'MAX_TRACKS', 1):
            with self.assertRaises(SubtitleError):
                subtitles.list_tracks(str(self.movie))

    def test_changes_during_read_rejected(self):
        original = subtitles._check
        calls = []
        def mutate(info):
            original(info)
            calls.append(1)
            # Two checks while enumerating, then one immediately before reading.
            if len(calls) == 3:
                os.utime(self.root / 'video.en.vtt', ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        # Windows guarded handles deny writes; inject a changing identity instead.
        if os.name == 'nt':
            self.skipTest('identity mutation test uses POSIX timestamps')
        with patch.object(subtitles, '_check', side_effect=mutate):
            with self.assertRaises(SubtitleError):
                subtitles.read_track(str(self.movie), 0)
