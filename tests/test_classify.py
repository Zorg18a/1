"""Compatibility examples for URL classification and canonical keys."""
import unittest
from core.classify import classify


class ClassifyTests(unittest.TestCase):
    def test_known_sources(self):
        cases = [
            ('https://www.senkuro.me/manga/one-piece/chapters', 'manga',
             'manga:one-piece', 'https://senkuro.me/manga/one-piece'),
            ('https://youtu.be/abc', 'video', 'https://www.youtube.com/watch?v=abc', None),
            ('https://www.youtube.com/watch?v=abc&list=xyz', 'video',
             'https://www.youtube.com/watch?v=abc', None),
            ('https://youtube.com/playlist?list=xyz', 'playlist',
             'https://www.youtube.com/playlist?list=xyz', None),
            ('https://youtube.com/@creator?x=1#section', 'playlist',
             'https://youtube.com/@creator', None),
            ('https://music.youtube.com/watch?v=abc', 'audio',
             'https://www.youtube.com/watch?v=abc', None),
            ('https://vimeo.com/123', 'video', 'https://vimeo.com/123', None),
            ('https://soundcloud.com/a/b', 'audio', 'https://soundcloud.com/a/b', None),
            ('https://artist.bandcamp.com/album/record', 'audio',
             'https://artist.bandcamp.com/album/record', None),
            ('https://example.org/feed.xml', 'podcast', 'https://example.org/feed.xml', None),
            ('https://open.spotify.com/show/123', 'podcast', 'https://open.spotify.com/show/123', None),
            ('https://f95zone.to/threads/game.123/page-2#post', 'game',
             'https://f95zone.to/threads/game.123/', None),
            ('https://artist.itch.io/game', 'game', 'https://artist.itch.io/game', None),
            ('https://example.org/page', 'unknown', 'https://example.org/page', None),
        ]
        for url, kind, key, norm in cases:
            with self.subTest(url=url):
                result = classify(url)
                self.assertEqual((result['kind'], result['key'], result.get('norm')), (kind, key, norm))

    def test_host_suffix_does_not_match_unrelated_domain(self):
        result = classify('https://notbandcamp.com/a')
        self.assertEqual(result['kind'], 'unknown')
        self.assertEqual(result['host'], 'notbandcamp.com')
