# gamelib: карточка игры из страницы темы (XenForo-форумы вроде f95zone), сравнение версий, ключи для сопоставления с установленными играми.
# Страница берётся из вашего браузера через расширение; здесь только разбор готового HTML.
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

STATUSES = {'completed': 'Завершена', 'abandoned': 'Заброшена', 'on hold': 'Приостановлена'}
ENGINES = {"ren'py", 'renpy', 'unity', 'rpgm', 'rpg maker', 'unreal engine', 'html', 'java', 'flash', 'qsp', 'webgl', 'tads', 'adrift', 'rags', 'wolf rpg', 'others'}
HOSTS = ('mega.nz', 'gofile.io', 'mediafire.com', 'workupload.com', 'pixeldrain.com', 'drive.google.com', 'mixdrop', 'anonfiles', 'zippyshare', 'dropbox.com', 'uploadhaven', 'krakenfiles', 'catbox.moe', 'buzzheavier', 'datanodes', 'vikingfile')
SUPPORT = ('patreon.com', 'subscribestar', 'itch.io', 'discord', 'twitter.com', 'x.com', 'steampowered.com', 'boosty.to', 'ko-fi.com', 'fanbox')
PREF = r"(?:Ren'Py|RenPy|Unity|RPGM|RPG Maker|Unreal Engine|HTML|Java|Flash|QSP|WebGL|Tads|ADRIFT|RAGS|Wolf RPG|Others|VN|Collection|Cheat Mod|Mod|Tool|Completed|Abandoned|On hold)"
HOSTNAMES = {'MEGA', 'WORKUPLOAD', 'BUZZHEAVIER', 'DATANODES', 'MIXDROP', 'PIXELDRAIN', 'VIKINGFILE', 'GOFILE', 'MEDIAFIRE', 'KRAKENFILES', 'BOWFILE', 'FILEQ', 'GDRIVE', 'DROPBOX', 'ANONFILES', 'UPLOADHAVEN', 'CATBOX'}
PLAT = r'^(Win(dows)?(\s*/\s*Linux)?|Linux|Mac(OS)?|Android|PC|iOS|Extras?|Cheats?|Patch(es)?)'
FIELD = re.compile(r'^\s*(Overview|Release Date|Developer|Version|Censored|OS|Language|Genre|Thread Updated|Platform)\s*:\s*(.*)$', re.I)


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self.h1, self.labels, self.tags, self.links, self.lines = {}, '', '', [], [], [], []
        self.rows = []; self._rl = []; self._skip = 0
        self._in_title = self._in_h1 = 0; self._label = None; self._tag = None; self._post = 0; self._depth = 0; self._post_done = False; self._buf = ''; self._a = None; self._h1_buf = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); cls = a.get('class') or ''
        if tag in ('script', 'style'): self._skip += 1
        if tag == 'meta' and (a.get('property') or a.get('name')): self.meta[(a.get('property') or a.get('name')).lower()] = a.get('content') or ''
        if tag == 'title': self._in_title = 1
        if tag == 'h1' and 'p-title-value' in cls: self._in_h1 = 1
        if self._in_h1 and tag == 'span' and 'label' in cls: self._label = ''
        if tag == 'a' and 'tagitem' in cls.lower(): self._tag = ''
        if tag == 'div' and 'bbWrapper' in cls and not self._post_done and not self._post: self._post = 1; self._depth = 1; return
        if self._post:
            if tag == 'div': self._depth += 1
            if tag in ('br', 'p', 'li', 'tr') or (tag == 'div'): self._flush()
            if tag == 'a' and a.get('href'): self._a = {'href': a['href'], 'text': ''}
            if tag == 'img' and not self.meta.get('_img') and (a.get('src') or a.get('data-src')): self.meta['_img'] = a.get('data-src') or a.get('src')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self._skip: self._skip -= 1
        if tag == 'title': self._in_title = 0
        if tag == 'h1' and self._in_h1: self._in_h1 = 0
        if tag == 'span' and self._label is not None:
            if self._label.strip(): self.labels.append(self._label.strip())
            self._label = None
        if tag == 'a' and self._tag is not None:
            t = self._tag.strip()
            if t and t not in self.tags: self.tags.append(t)
            self._tag = None
        if self._post:
            if tag == 'a' and self._a: self.links.append(self._a); self._rl.append(self._a); self._a = None
            if tag in ('p', 'li', 'tr'): self._flush()
            if tag == 'div':
                self._depth -= 1
                if self._depth <= 0: self._flush(); self._post = 0; self._post_done = True

    def handle_data(self, d):
        if self._skip: return
        if self._in_title: self.title += d
        if self._in_h1 and self._label is None: self._h1_buf += d
        if self._label is not None: self._label += d
        if self._tag is not None: self._tag += d
        if self._post:
            self._buf += d
            if self._a is not None: self._a['text'] += d

    def _flush(self):
        t = re.sub(r'\s+', ' ', self._buf).strip()
        if t: self.lines.append(t); self.rows.append((t, list(self._rl)))
        self._buf = ''; self._rl = []


def _cut(t, n):
    """Обрезка описания до целого предложения."""
    t = re.sub(r'\s*(Spoiler|Спойлер)\b.*$', '', t or '', flags=re.S).strip()
    if len(t) <= n: return t
    c = t[:n]; k = max(c.rfind('. '), c.rfind('! '), c.rfind('? '))
    return c[:k + 1] if k > n // 2 else c.rsplit(' ', 1)[0] + '…'


def vnums(text):
    """'v0.3.1b' -> (0, 3, 1); 'Demo' -> (0,); 'Ch.4' -> (4,); нет цифр и не демо -> None"""
    t = str(text or '')
    m = re.search(r'\d+(?:\.\d+)*', t)
    if m: return tuple(int(x) for x in m.group(0).split('.'))
    return (0,) if re.search(r'demo|prologue|prelude|teaser', t, re.I) else None


def newer(a, b):
    """True, если версия a новее b; при неизвестных версиях — False (не гадаем)."""
    x, y = vnums(a), vnums(b)
    if x is None or y is None: return False
    n = max(len(x), len(y)); return x + (0,) * (n - len(x)) > y + (0,) * (n - len(y))


def thread_key(url):
    """Нормальный адрес темы: https://host/threads/<slug>.<id>/ без страниц и якорей; иначе адрес без якоря."""
    u = urlparse(url); m = re.match(r'^(/threads/[^/]*?\.?\d+)(/|$)', u.path)
    return f'{u.scheme}://{u.netloc}{m.group(1)}/' if m else url.split('#')[0]


def is_blocked(html):
    """Вместо страницы пришла проверка Cloudflare («Just a moment…»)."""
    h = html or ''
    return bool(re.search(r'<title>\s*Just a moment', h, re.I) or (('cf-chl' in h or 'challenge-platform' in h) and 'og:title' not in h))


def parse_thread(html, url=''):
    if is_blocked(html): return {'name': '', 'blocked': True, 'version': '', 'genres': [], 'links': []}
    p = _P()
    try: p.feed(html or ''); p.close()
    except Exception: pass
    raw = (p.meta.get('og:title') or p._h1_buf or p.title or '').strip()
    raw = re.sub(r'^\(\d+\)\s*', '', raw)                                   # счётчик уведомлений вкладки: «(74) …»
    raw = re.sub(r'\s*[|–—-]\s*F95zone.*$', '', raw, flags=re.I).strip()
    pm = re.match(r'^((?:' + PREF + r'\s+-\s+)+)', raw, re.I); tprefix = []                # «Unity - Название [версия] [автор]»
    if pm: tprefix = [x.strip() for x in re.split(r'\s+-\s+', pm.group(1).strip(' -')) if x.strip()]; raw = raw[pm.end():]
    brackets = re.findall(r'\[([^\]]+)\]', raw); name = re.sub(r'\s*\[[^\]]*\]', '', raw).strip(' -:')
    fields = {}
    for n, ln in enumerate(p.lines):
        m = FIELD.match(ln)
        if m and m.group(1).lower() not in fields:
            v = m.group(2).strip()
            if not v and m.group(1).lower() == 'overview':          # описание идёт со следующей строки
                nxt = []
                for x in p.lines[n + 1:n + 6]:
                    if FIELD.match(x) or re.match(r'^(Spoiler|Спойлер|Download|Changelog)', x, re.I): break
                    nxt.append(x)
                v = ' '.join(nxt)
            fields[m.group(1).lower()] = v
    labels = [x for x in p.labels] + [x for x in tprefix if x not in p.labels]
    status = next((STATUSES[x.lower()] for x in labels if x.lower() in STATUSES), '')
    engine = next((x for x in labels if x.lower() in ENGINES), '')
    ver = brackets[0] if brackets else fields.get('version', '')
    dev = (brackets[1] if len(brackets) > 1 else '') or re.split(r'\s+[-–]\s+', fields.get('developer', ''))[0].strip()
    genres = list(p.tags)
    for g in re.split(r'\s*,\s*', fields.get('genre', '')):
        if g and g.lower() not in [x.lower() for x in genres]: genres.append(g)
    cover = p.meta.get('og:image') or p.meta.get('twitter:image') or p.meta.get('_img') or ''
    if cover and url: cover = urljoin(url, cover)
    links, support, platform, seen = [], [], '', set()
    for text, items in p.rows:
        good = []; dev_row = bool(re.match(r'^(Developer|Support|Links?)\b', text, re.I))
        for l in items:
            h = l['href']; hu = urljoin(url, h) if url else h; host = (urlparse(hu).hostname or '').lower(); txt = re.sub(r'\s+', ' ', l['text']).strip()
            if not hu.startswith('http') or any(x in hu.lower() for x in ('/members/', '/threads/', 'attachments.f95zone')): continue
            if dev_row or any(x in hu.lower() for x in SUPPORT):          # ссылки автора: Patreon, itch.io и т. п. — не скачивание
                if len(support) < 12 and hu not in [s['url'] for s in support]: support.append({'label': txt[:30] or host, 'url': hu})
                continue
            known = next((x for x in HOSTS if x in hu.lower() or x.split('.')[0] in txt.lower()), '')
            if known or re.search(r'/(dl|masked)/', hu) or txt.upper() in HOSTNAMES: good.append((hu, txt, known or txt.lower() or host))
        if not good:
            if not items and re.match(PLAT + r'\s*:?\s*$', text, re.I): platform = text.rstrip(': ')
            continue
        first = text.find(good[0][1]); row = text[:first].strip(' :-') if first > 0 else ''
        if re.match(PLAT, row, re.I): platform = row.rstrip(': '); row = ''                 # строка «Win/Linux: …» сама задаёт платформу
        grp = ' · '.join(x for x in (platform, row) if x)
        for hu, txt, host in good:
            if hu not in seen: seen.add(hu); links.append({'label': txt[:40] or host, 'url': hu, 'host': host, 'group': grp})
    uniq = links
    desc = fields.get('overview') or p.meta.get('og:description', '')
    return {'name': name or raw, 'version': ver, 'developer': dev, 'engine': engine, 'status': status, 'genres': genres[:60], 'cover': cover,
            'os': fields.get('os', ''), 'language': fields.get('language', ''), 'release': fields.get('release date', ''), 'censored': fields.get('censored', ''),
            'desc': _cut(desc, 500), 'support': support, 'links': uniq[:150], 'prefixes': labels, 'thread': thread_key(url) if url else ''}
