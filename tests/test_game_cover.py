"""Choosing game artwork must not blindly select the site logo."""
import unittest
from core import gamelib


URL = 'https://f95zone.to/threads/example.123/'


class GameCoverTests(unittest.TestCase):
    def parse(self, post='', meta=''):
        html = ('<meta property="og:title" content="Unity - Example [1.2] [Studio]">' + meta +
                '<div class="bbWrapper">' + post + '</div>')
        return gamelib.parse_thread(html, URL)

    def test_first_post_image_wins_over_site_logo(self):
        result = self.parse('<img class="smilie" src="/styles/smile.png" width="18" height="18">'
                            '<img src="/styles/placeholder.png" data-src="https://images.example/game.jpg">',
                            '<meta property="og:image" content="/styles/f95zone/logo.png">')
        self.assertEqual(result['cover'], 'https://images.example/game.jpg')
        self.assertEqual((result['name'], result['version']), ('Example', '1.2'))

    def test_uses_social_image_when_no_post_image(self):
        result = self.parse(meta='<meta property="og:image" content="/covers/example.jpg">')
        self.assertEqual(result['cover'], 'https://f95zone.to/covers/example.jpg')

    def test_rejects_obvious_branding_small_images_and_invalid_schemes(self):
        post = ('<img src="/avatar/portrait.jpg"><img class="site-logo" src="/img/a.png">'
                '<img src="/tiny.jpg" width="20"><img src="data:image/png;base64,AAAA">')
        result = self.parse(post, '<meta property="og:image" content="/static/logo.png">')
        self.assertEqual(result['cover'], '')

    def test_no_use_of_images_after_first_post(self):
        html = ('<meta property="og:title" content="Example [1]">'
                '<div class="bbWrapper">No image</div>'
                '<div class="bbWrapper"><img src="/other-game.jpg"></div>')
        self.assertEqual(gamelib.parse_thread(html, URL)['cover'], '')

    def test_invalid_candidate_does_not_prevent_later_good_image(self):
        result = self.parse('<img data-src="javascript:alert(1)" src="/favicon.ico">'
                            '<img src="/images/poster.jpg">')
        self.assertEqual(result['cover'], 'https://f95zone.to/images/poster.jpg')


if __name__ == '__main__': unittest.main()
