"""Synthetic Pornolab markup and source persistence; no network or user data."""
import os
import subprocess
import sys
import tempfile
import unittest

from core.pornolab import parse_topic, topic_url

URL = 'https://pornolab.net/forum/viewtopic.php?t=3282477'


class PornolabTests(unittest.TestCase):
    def test_topic_url_is_exact_and_canonical(self):
        self.assertEqual(topic_url(URL + '&start=20#post'), URL)
        for value in ('http://pornolab.net/forum/viewtopic.php?t=1',
                      'https://pornolab.net.evil.test/forum/viewtopic.php?t=1',
                      'https://user@pornolab.net/forum/viewtopic.php?t=1',
                      'https://pornolab.net:444/forum/viewtopic.php?t=1',
                      'https://pornolab.net/forum/viewtopic.php?t=1&t=2',
                      'https://pornolab.net/forum/viewtopic.php?t=0',
                      'https://pornolab.net/forum/viewtopic.php?t=abc',
                      'https://pornolab.net/forum/other.php?t=1', None):
            with self.subTest(value=value): self.assertIsNone(topic_url(value))

    def test_first_post_fields_and_image_ignore_site_logo_and_replies(self):
        html = ('<meta property="og:image" content="https://pornolab.net/logo.png">'
                '<h1 class="maintitle"><a>Тестовая игра</a></h1>'
                '<div class="post_body"><div class="post-user-message">'
                '<var class="postImg" title="https://images.example/cover.jpg"></var>'
                '<span class="post-b">Название игры:</span> Тестовая игра<br>'
                '<span class="post-b">Версия:</span> 1.2<br>'
                '<span class="post-b">Жанр:</span> RPG, Приключения<br>'
                '<span class="post-b">Разработчик:</span> Студия<br>'
                '</div></div><div class="post_body">Версия: 9.9<br>'
                '<img src="https://images.example/reply.jpg"></div>')
        result = parse_topic(html, URL)
        self.assertEqual(result['name'], 'Тестовая игра')
        self.assertEqual(result['version'], '1.2')
        self.assertEqual(result['developer'], 'Студия')
        self.assertEqual(result['genres'], ['RPG', 'Приключения'])
        self.assertEqual(result['cover'], 'https://images.example/cover.jpg')
        self.assertEqual(result['thread'], URL)

    def test_no_fake_success_for_login_truncated_or_unrelated_pages(self):
        for html in ('<h1 class="maintitle">Вход</h1>',
                     '<h1 class="maintitle">Игра</h1><div class="post_body">Текст',
                     '<div class="post_body">Текст</div>',
                     '<h1 class="maintitle">Игра</h1><div>Текст</div>'):
            self.assertIsNone(parse_topic(html, URL))
        self.assertIsNone(parse_topic('<h1 class="maintitle">X</h1><div class="post_body"></div>',
                                      'https://example.org/forum/viewtopic.php?t=1'))

    def test_unknown_fields_stay_empty_and_metadata_logo_is_not_cover(self):
        html = ('<meta property="og:image" content="/logo.png">'
                '<h1 class="maintitle">Имя темы</h1><div class="post_body">Описание без полей</div>')
        result = parse_topic(html, URL)
        self.assertEqual((result['name'], result['version'], result['genres'], result['cover']),
                         ('Имя темы', '', [], ''))

    def test_existing_app_can_save_topic_as_link_across_restart(self):
        first = r'''
from legacy import app
try:
    url = 'https://pornolab.net/forum/viewtopic.php?t=3282477'
    batch, count = app.inbox_add([{'id': 1, 'url': url, 'title': 'Пример темы'}], False, 'test')
    row = app.sql('select * from inbox where batch=?', (batch,))[0]
    assert count == 1 and row['kind'] == 'unknown' and row['action'] == 'link'
    result = app.inbox_confirm({'batch': batch, 'close': False, 'rows': [
        {'id': row['id'], 'kind': 'unknown', 'action': 'link'}]})
    assert result['links'] == 1
finally: app.db.close()
'''
        second = r'''
from legacy import app
try:
    rows = app.sql('select kind,src from items where src=?', ('https://pornolab.net/forum/viewtopic.php?t=3282477',))
    assert len(rows) == 1 and rows[0]['kind'] == 'link'
finally: app.db.close()
'''
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, MEDIAHUB_DATA_DIR=directory)
            for script in (first, second):
                subprocess.run([sys.executable, '-c', script], env=env, check=True, timeout=30)


if __name__ == '__main__': unittest.main()
