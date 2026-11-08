import unittest
from core import gamelib
from legacy import gamesweep


class GameLogicTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(gamelib.newer('v1.2', '1.1.9'))
        self.assertFalse(gamelib.newer('1.0', '1.0.0'))
        self.assertFalse(gamelib.newer('unknown', '1.0'))
        self.assertEqual(gamelib.vnums('Demo'), (0,))

    def test_thread_and_blocked_page(self):
        self.assertEqual(gamelib.thread_key('https://f95zone.to/threads/game.123/page-2#post'),
                         'https://f95zone.to/threads/game.123/')
        self.assertTrue(gamelib.parse_thread('<title>Just a moment...</title>')['blocked'])

    def test_thread_metadata(self):
        html = '<meta property="og:title" content="Unity - Game [1.2] [Studio]">'
        result = gamelib.parse_thread(html, 'https://f95zone.to/threads/game.123/')
        self.assertEqual((result['name'], result['version'], result['developer']), ('Game', '1.2', 'Studio'))
        self.assertEqual(result['engine'], 'Unity')

    def test_scanning_and_grouping(self):
        games = [{'name': n, 'path': '/tmp/' + n, 'type': 'archive', 'size': 10, 'mtime': 1}
                 for n in ('Game-v1.0.zip', 'Game-v2.0.zip')]
        group = gamesweep.build_groups(games)[0]
        self.assertEqual([row['status'] for row in group['members']], ['оставить', 'старая'])
        self.assertEqual(gamesweep.parse_name('Game 2 v1.0.zip')['key'], 'game2')


if __name__ == '__main__':
    unittest.main()
