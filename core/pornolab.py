"""Experimental offline parser for Pornolab topic pages; not wired to the app.

Only a complete topic with a title and first post is accepted. Actual game-topic
markup and artwork availability still require verification against a real page.
"""
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit

from core import game_cover


def topic_url(value):
    """Recognize the one HTTPS forum topic address shape without trusting other hosts."""
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.hostname != 'pornolab.net' or url.username is not None
                or url.password is not None or url.port not in (None, 443)
                or url.path != '/forum/viewtopic.php'):
            return None
        ids = parse_qs(url.query, keep_blank_values=True).get('t', [])
        if len(ids) != 1 or not re.fullmatch(r'[1-9][0-9]{0,11}', ids[0]):
            return None
        return 'https://pornolab.net/forum/viewtopic.php?t=' + ids[0]
    except ValueError:
        return None


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.heading = False
        self.post_depth = 0
        self.post_seen = False
        self.complete = False
        self.ignored = 0
        self.text = []
        self.images = []
        self._vars = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if tag == 'h1' and 'maintitle' in classes and not self.title:
            self.heading = True
        if tag == 'div':
            if self.post_depth:
                self.post_depth += 1
            elif not self.post_seen and 'post_body' in classes:
                self.post_seen = True
                self.post_depth = 1
        if not self.post_depth:
            return
        if tag in ('script', 'style'):
            self.ignored += 1
        if self.ignored:
            return
        if tag in ('br', 'p', 'li', 'div', 'tr'):
            self.text.append('\n')
        if tag == 'var':
            index = len(self.images) if 'postImg' in classes and len(self.images) < 100 else None
            self._vars.append(index)
            if index is not None:
                self.images.append({'src': attrs.get('title') or ''})
        if tag == 'img' and len(self.images) < 100:
            index = next((i for i in reversed(self._vars) if i is not None), None)
            if index is None:
                self.images.append(attrs)
            else:
                self.images.insert(index, attrs)
                self._vars = [i + 1 if i is not None and i >= index else i for i in self._vars]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.heading = False
        if self.post_depth:
            if tag == 'var' and self._vars:
                self._vars.pop()
            if tag in ('script', 'style') and self.ignored:
                self.ignored -= 1
            if not self.ignored and tag in ('p', 'li', 'div', 'tr'):
                self.text.append('\n')
            if tag == 'div':
                self.post_depth -= 1
                if not self.post_depth:
                    self.complete = True

    def handle_data(self, data):
        if self.heading:
            self.title.append(data)
        if self.post_depth and not self.ignored:
            self.text.append(data)


def parse_topic(html, url):
    """Parse tentative metadata; return None on unsupported or incomplete pages."""
    if not topic_url(url) or not isinstance(html, str) or len(html) > 3_000_000:
        return None
    page = _Page()
    try:
        page.feed(html)
        page.close()
    except (ValueError, RecursionError):
        return None
    title = re.sub(r'\s+', ' ', ''.join(page.title)).strip()
    if not title or not page.complete:
        return None
    fields = {}
    labels = {'название игры': 'name', 'название': 'name', 'версия игры': 'version',
              'версия': 'version', 'жанр': 'genre', 'жанры': 'genre',
              'разработчик': 'developer', 'год выпуска': 'release', 'описание': 'desc'}
    for line in ''.join(page.text).splitlines():
        key, sep, value = line.partition(':')
        key, value = ' '.join(key.lower().split()), ' '.join(value.split())
        if sep and key in labels and value:
            fields.setdefault(labels[key], value[:2000])
    genres = [part.strip() for part in re.split(r'[,;/]', fields.get('genre', '')) if part.strip()]
    return {'name': fields.get('name', title)[:300], 'version': fields.get('version', '')[:150],
            'developer': fields.get('developer', '')[:300], 'release': fields.get('release', '')[:100],
            'genres': genres[:60], 'desc': fields.get('desc', ''), 'cover': game_cover.choose(page.images, {}, url),
            'thread': topic_url(url)}
