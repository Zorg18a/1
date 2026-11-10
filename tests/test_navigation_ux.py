"""Accessible names for compact navigation, independent of hidden text labels."""
from html.parser import HTMLParser
from pathlib import Path
import unittest


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_nav = False
        self.links = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav' and attrs.get('aria-label') == 'Разделы':
            self.in_nav = True
        if self.in_nav and tag == 'a':
            self.links[attrs.get('href')] = attrs

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_nav = False


class NavigationUxTests(unittest.TestCase):
    def test_main_navigation_has_names_and_tooltips_when_visible_text_is_hidden(self):
        parser = NavigationParser()
        parser.feed((Path(__file__).resolve().parents[1] / 'ui' / 'index.html').read_text(encoding='utf8'))
        expected = {'#library': 'Библиотека', '#inbox': 'Входящие', '#downloads': 'Загрузки',
                    '#games': 'Игры', '#settings': 'Настройки'}
        self.assertEqual(set(parser.links), set(expected))
        for path, name in expected.items():
            with self.subTest(path=path):
                self.assertEqual(parser.links[path].get('aria-label'), name)
                self.assertEqual(parser.links[path].get('title'), name)
