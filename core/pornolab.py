"""Conservative Pornolab topic parsing from HTML obtained by the user's browser.

Page layout can vary. Missing metadata remains unknown; access failures must not
be treated as an empty game. Real network/extension behavior needs user testing.
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
              'версия': 'version', 'жанр': 'genre', 'жанры': 'genre', 'теги': 'genre',
              'разработчик': 'developer', 'год выпуска': 'release', 'дата релиза': 'release', 'описание': 'desc'}
    for line in ''.join(page.text).splitlines():
        key, sep, value = line.partition(':')
        key, value = ' '.join(key.lower().split()), ' '.join(value.split())
        if sep and key in labels and value:
            fields.setdefault(labels[key], value[:2000])
    # Example layout: Game [1.0] (Developer) [status] [year, tags] [languages].
    match = re.match(r'^(.+?)\s*\[((?:v|ver\.?\s*)?\d[^\]]{0,60})\]\s*(?:\(([^)]{1,200})\))?', title, re.I)
    name = match.group(1).strip() if match else title
    version = match.group(2).strip() if match else ''
    developer = (match.group(3) or '').strip() if match else ''
    genres = [part.strip() for part in re.split(r'[,;/]', fields.get('genre', '')) if part.strip()]
    if not genres:
        groups = re.findall(r'\[([^\]]+)\]', title)
        tags = next((g for g in groups if re.match(r'^\s*(?:19|20)\d{2}\s*,', g)), '')
        genres = [p.strip() for p in tags.split(',')[1:] if p.strip()]
    preferred = [a for a in page.images if 'postImgAligned' in (a.get('class') or '').split()]
    cover = game_cover.choose(preferred or page.images, {}, url)
    return {'name': fields.get('name', name)[:300], 'version': fields.get('version', version)[:150],
            'developer': fields.get('developer', developer)[:300], 'release': fields.get('release', '')[:100],
            'genres': genres[:60], 'desc': fields.get('desc', ''), 'cover': cover, 'thread': topic_url(url)}


def find_card(sql, find_game, key, name, thread):
    canonical = topic_url(thread)
    if canonical:
        rows = sql("select * from items where kind='game' and src=?", (canonical,))
        if len(rows) > 1:
            raise ValueError('Для темы найдено несколько карточек; проверьте их вручную')
        if rows:
            return rows[0]
    return find_game(key, name)


def safe_metadata(meta, row, info, thread):
    """Do not merge a Pornolab topic into an unrelated or unlinked existing game."""
    canonical = topic_url(thread)
    if not canonical or row is None:
        return meta
    old = info.get('meta', {}) if isinstance(info, dict) else {}
    if not isinstance(old, dict):
        raise ValueError('Существующая карточка содержит неизвестные метаданные')
    sources = [s for s in (row['src'], old.get('thread')) if s]
    if not sources or any(topic_url(s) != canonical for s in sources):
        raise ValueError('Похожая игра уже существует: проверьте карточку и ссылку вручную')
    merged = dict(meta)
    for key in ('version', 'developer', 'release', 'genres', 'desc', 'cover'):
        if not merged.get(key) and old.get(key):
            merged[key] = old[key]
    return merged
