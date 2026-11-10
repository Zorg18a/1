# MediaHub v2: локальный загрузчик + библиотека. Движок — yt-dlp[default], ffmpeg/deno берутся из папки ffmpeg рядом.
import sys, base64, hmac, secrets, http.client, json, logging, os, re, subprocess, shutil, sqlite3, threading, time, webbrowser, urllib.request, itertools, http.cookiejar, mimetypes
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin, unquote, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from storage.database import open_database, execute
from storage import cover_cache, cover_download, game_tags, incoming_downloads, delete_files, library_search, game_scan
from core import gamelib, byte_range, media_outcome, delete_guard, inbox_lock, legacy_reader_progress
from core.classify import classify
from core.game_sources import quick_game_request
from core.game_tags import save_tags_request
from core.update_preview import preview_request
from core.update_inspect import inspect_request
from core.job_queue import JobQueue
from legacy import gamesweep, media_subtitles, player_preview
mimetypes.add_type('image/avif', '.avif'); mimetypes.add_type('text/javascript', '.js')
BASE = Path(os.environ.get('MEDIAHUB_DATA_DIR') or (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent))
BASE.mkdir(parents=True, exist_ok=True)
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
FF = BASE / 'ffmpeg'; CFG = BASE / 'settings.json'
if FF.exists(): os.environ['PATH'] = str(FF) + os.pathsep + os.environ['PATH']  # ffmpeg, ffprobe, deno
cfg = {'folder': str(Path.home() / 'Downloads' / 'MediaHub'), 'workers': 3, 'skip': True, 'cookie_file': '', 'cookie_browser': '', 'games_root': '', 'games_layout': 'auto', 'show_browser': False, 'browser': 'msedge', 'limit_mb': 0, 'manga_via': 'auto', 'games_check_hours': 0,
       'res': 'best', 'afmt': 'mp3', 'subs_on': False, 'subs_langs': 'ru,en', 'thumbs': True, 'depth': 1, 'maxp': 100, 'videos': True}
if CFG.exists(): cfg.update(json.loads(CFG.read_text('utf-8')))
db, lock = open_database(BASE / 'library.db')
jobs, ids, prev, _op = {}, itertools.count(1), {}, [None]
VID = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv', '.m4v'}; AUD = {'.mp3', '.m4a', '.opus', '.flac', '.wav', '.ogg', '.aac'}
def sql(s, a=()): return execute(db, lock, s, a)
def safe(s): return re.sub(r'[\\/:*?"<>|]+', '_', str(s or '')).strip()[:100] or 'Unknown'
def root(sub):
    p = Path(cfg['folder']) / sub; p.mkdir(parents=True, exist_ok=True); return p
def thumb_of(p):
    for e in ('.jpg', '.jpeg', '.png', '.webp'):
        if Path(p).with_suffix(e).exists(): return str(Path(p).with_suffix(e))
    return ''
def add(title, author, topic, kind, path, url, rt='', thumb=''):
    sz = sum(f.stat().st_size for f in Path(rt).rglob('*') if f.is_file()) if rt else os.path.getsize(path)
    sql('insert into items(title,author,topic,kind,path,root,url,size,thumb) values(?,?,?,?,?,?,?,?,?) on conflict(url) do update set title=excluded.title,path=excluded.path,root=excluded.root,size=excluded.size,thumb=excluded.thumb,author=case when items.kind=\'link\' then excluded.author else items.author end,topic=case when items.kind=\'link\' then excluded.topic else items.topic end,kind=excluded.kind',
        (title, author, topic, kind, str(path), str(rt), url, sz, thumb or ('' if rt else thumb_of(path))))
def scan():  # подхватывает файлы, которых нет в базе (в т.ч. скачанные раньше)
    have = {r['path'] for r in sql('select path from items')}
    for kind, sub, ex in (('video', 'Video', VID), ('audio', 'Audio', AUD)):
        d = root(sub)
        for f in d.rglob('*'):
            if f.suffix.lower() in ex and str(f) not in have and not re.search(r'\.f\d+\.', f.name):
                add(f.stem, f.parent.name if f.parent != d else 'Unknown', 'Разное', kind, f, 'file:' + str(f))
NOWIN = 0x08000000 if os.name == 'nt' else 0; _bf = [False]
def backfill():  # обложка-кадр для видео, у которых её нет (старые загрузки, обложки отключали)
    if _bf[0]: return
    _bf[0] = True
    try:
        ff = shutil.which('ffmpeg')
        if not ff: return
        for r in sql("select id,path from items where kind='video' and (thumb is null or thumb='')"):
            p = Path(r['path']); out = p.with_suffix('.jpg')
            if not p.exists(): continue
            for ss in ('5', '0'):  # сначала 5-я секунда, для коротких роликов первый кадр
                if out.exists(): break
                try: subprocess.run([ff, '-y', '-ss', ss, '-i', str(p), '-frames:v', '1', '-vf', 'scale=480:-2', '-q:v', '4', str(out)], capture_output=True, timeout=60, creationflags=NOWIN)
                except Exception: pass
            if out.exists(): sql('update items set thumb=? where id=?', (str(out), r['id']))
    finally: _bf[0] = False
def fmt(kind, r): return 'bestaudio/best' if kind == 'audio' else ('bv*+ba/b' if r == 'best' else f'bv*[height<={r}]+ba/b[height<={r}]')
def base():
    o = {'quiet': True, 'no_warnings': True, 'remote_components': ['ejs:github']}
    if cfg['cookie_file']: o['cookiefile'] = cfg['cookie_file']
    elif cfg['cookie_browser']: o['cookiesfrombrowser'] = (cfg['cookie_browser'],)
    if FF.exists(): o['ffmpeg_location'] = str(FF)
    return o
# ---------- видео / аудио ----------
def media(job):  # видео/аудио; плейлисты и каналы разворачиваются и качаются несколькими потоками сразу
    import yt_dlp
    audio = job['kind'] == 'audio'; n, errs, part, sp, lk = [0], [], {}, {}, threading.Lock(); st = {'done': 0, 'total': 1}
    class L:
        def debug(s, m): pass
        def warning(s, m): pass
        def error(s, m): errs.append(m)
    def post(d):
        if d['postprocessor'] == 'MoveFiles' and d['status'] == 'finished':
            i = d['info_dict']
            with lk: n[0] += 1
            add(i.get('title'), i.get('uploader') or i.get('channel') or 'Unknown',
                job['topic'] or (i.get('categories') or i.get('tags') or ['Разное'])[0], job['kind'], i['filepath'], i.get('webpage_url') or job['url'])
    def run(url, tid):
        def hook(d):
            if job['cancel']: raise yt_dlp.utils.DownloadCancelled('отменено')
            if d['status'] == 'downloading':
                t = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                with lk:
                    if t: part[tid] = d['downloaded_bytes'] / t
                    sp[tid] = d.get('speed') or 0; job['speed'] = sum(sp.values()); job['_ts'] = time.time(); job['eta'] = d.get('eta') or 0
                    job['title'] = d['info_dict'].get('title', ''); job['pct'] = min(99, int((st['done'] + sum(part.values())) * 100 / st['total']))
        o = base(); pps = []
        o.update({'format': fmt(job['kind'], job['res']), 'ignoreerrors': 'only_download', 'concurrent_fragment_downloads': 8, 'logger': L(),
                  'outtmpl': str(root('Audio' if audio else 'Video') / '%(uploader,channel|Unknown)s' / '%(title).120B.%(ext)s'),
                  'progress_hooks': [hook], 'postprocessor_hooks': [post]})
        if audio: pps.append({'key': 'FFmpegExtractAudio', 'preferredcodec': job['afmt']})
        else: o['merge_output_format'] = 'mp4'
        if job['subs'] and not audio:
            o.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=[x.strip() for x in job['subs'].split(',')], subtitlesformat='srt/best', sleep_interval_subtitles=1)
            pps.append({'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'})
        if job['thumbs']:
            o['writethumbnail'] = True; pps += [{'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'}, {'key': 'EmbedThumbnail'}]
        o['postprocessors'] = pps
        if float(cfg.get('limit_mb') or 0): o['ratelimit'] = int(float(cfg['limit_mb']) * 1048576 / max(1, min(st['total'], int(cfg.get('workers') or 3))))
        if cfg['skip']: o['download_archive'] = str(BASE / f"archive_{job['kind']}.txt")
        with yt_dlp.YoutubeDL(o) as y: media_outcome.checked_download(y, url)
        with lk: st['done'] += 1; part.pop(tid, None); sp.pop(tid, None)
    urls = [job['url']]
    if not re.search(r'(youtube\.com/watch\?v=[\w-]+|youtu\.be/[\w-]+)$', job['url']):  # одиночное видео YouTube не проверяем: экономим запрос
        try:
            fo = base(); fo.update(extract_flat='in_playlist', skip_download=True)
            with yt_dlp.YoutubeDL(fo) as y: t = y.extract_info(job['url'], download=False)
            if t and t.get('_type') == 'playlist':
                us = media_outcome.playlist_urls(t, errs)
                if len(us) > 1: urls = us
        except Exception as e: errs.append(str(e) or 'не удалось проверить список элементов')
    st['total'] = len(urls)
    if len(urls) == 1: run(urls[0], 0)
    else:
        job['title'] = f'список: {len(urls)} видео'
        with ThreadPoolExecutor(max(1, int(cfg.get('workers') or 3))) as ex:
            for f in [ex.submit(run, u, k) for k, u in enumerate(urls)]:
                try: f.result()
                except Exception as e: errs.append(str(e) or 'Ошибка загрузки элемента')
    scan(); backfill(); media_outcome.mark_partial(job, n[0], errs)
    if not n[0] and not job['cancel']:
        if errs: raise RuntimeError(errs[-1])
        job['final'] = 'пропущено: уже скачано'

# ---------- сайт офлайн (страницы + видео) ----------
UA = {'User-Agent': 'Mozilla/5.0'}
VEXT = ('.mp4', '.webm', '.m4v', '.mov', '.mkv', '.m3u8', '.mpd')
VH = re.compile(r'youtube\.com|youtu\.be|vimeo\.com|rutube\.ru|vk\.com/video|vkvideo\.ru|dailymotion\.com|ok\.ru/video|twitch\.tv|bilibili\.com|player\.', re.I)
SKIP = re.compile(r'\.(jpe?g|png|gif|webp|svg|pdf|zip|rar|7z|mp3|mp4|webm|css|js|ico|exe)(\?|$)', re.I)

def guard(u):  # блокируем localhost и локальную сеть (в т.ч. после редиректов)
    import socket, ipaddress
    p = urlparse(u)
    if p.scheme not in ('http', 'https') or not p.hostname: raise ValueError('bad url')
    if os.environ.get('MEDIAHUB_TEST_ALLOW_LOCAL') == '1': return
    for a in socket.getaddrinfo(p.hostname, p.port or 80):
        ip = ipaddress.ip_address(a[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise ValueError('локальный адрес заблокирован')

def opener():
    if not _op[0]:
        jar = http.cookiejar.MozillaCookieJar()
        if cfg['cookie_file']:
            try: jar.load(cfg['cookie_file'], ignore_discard=True, ignore_expires=True)
            except Exception: pass
        _op[0] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return _op[0]

def fetch(u):
    guard(u)
    with opener().open(urllib.request.Request(u, headers=UA), timeout=20) as r:
        guard(r.geturl()); return r.read(), r.headers.get('Content-Type', '')

def stream(job, u, dest, tot, t0):  # большие видеофайлы пишем кусками
    guard(u); dest.parent.mkdir(parents=True, exist_ok=True)
    with opener().open(urllib.request.Request(u, headers=UA), timeout=30) as r, open(dest, 'wb') as f:
        guard(r.geturl())
        while not job['cancel']:
            c = r.read(1 << 20)
            if not c: break
            f.write(c); tot[0] += len(c); job['speed'] = tot[0] / max(1, time.time() - t0)

def grab(job, u, out, vids):  # YouTube, Vimeo, VK, Rutube, потоки m3u8/mpd и т.д. через yt-dlp
    if u in vids: return vids[u]
    vids[u] = []
    try:
        import yt_dlp
        def hk(d):
            if job['cancel']: raise yt_dlp.utils.DownloadCancelled('отменено')
            if d['status'] == 'downloading': job['speed'] = d.get('speed') or 0; job['title'] = 'видео: ' + str(d['info_dict'].get('title', ''))
        o = base(); o.update(format='bv*+ba/b', merge_output_format='mp4', noplaylist=True, ignoreerrors=True, progress_hooks=[hk],
                             outtmpl=str(out / '_videos' / '%(title).80B [%(id)s].%(ext)s'))
        with yt_dlp.YoutubeDL(o) as y: i = y.extract_info(u, download=True)
        for e in ([x for x in i.get('entries', []) if x] if (i or {}).get('_type') == 'playlist' else [i] if i else []):
            p = (e.get('requested_downloads') or [{}])[0].get('filepath') or e.get('filepath')
            if p and os.path.exists(p):
                vids[u].append(Path(p)); add(e.get('title'), urlparse(job['url']).netloc, job['topic'] or 'Сайты', 'video', p, e.get('webpage_url') or u)
    except Exception: pass
    return vids[u]

def crawl(job):
    start = job['url']; h = urlparse(start).netloc; out = root('Sites') / safe(h); t0 = time.time()
    sel = list(job.get('sel') or []); cap = len(sel) or int(job.get('maxp') or 100)
    seen, qd, n, first, title, tot, vids, vloc, lim, cover = set(), set(sel or [start]), 0, None, h, [0], {}, {}, [False], ''
    pages = [(u, 0) for u in sel] if sel else [(start, 0)]
    def lp(u):
        p = urlparse(u); path = unquote(p.path) or '/'
        if path.endswith('/'): path += 'index.html'
        elif '.' not in path.rsplit('/', 1)[-1]: path += '/index.html'
        if p.query: path = re.sub(r'(\.\w+)$', '_' + re.sub(r'\W', '', p.query)[:20] + r'\1', path)
        return out / safe(p.netloc) / Path(*[safe(x) for x in path.strip('/').split('/')])
    def rel(u, cur): return os.path.relpath(lp(u), cur.parent).replace(os.sep, '/')
    def relp(p, cur): return os.path.relpath(p, cur.parent).replace(os.sep, '/')
    def save(u, data):
        f = lp(u); f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(data); tot[0] += len(data); job['speed'] = tot[0] / max(1, time.time() - t0)
    def css(s, base_):
        def r(m):
            u = urljoin(base_, m.group(2))
            if not u.startswith('http'): return m.group(0)
            asset(u); return 'url(%s%s%s)' % (m.group(1), rel(u, lp(base_)), m.group(1))
        return re.sub(r'url\((["\']?)(.*?)\1\)', r, s)
    apool = ThreadPoolExecutor(8); futs = []; slk = threading.Lock()
    def _asset(u):
        try:
            d, t = fetch(u)
            if 'css' in t: d = css(d.decode('utf-8', 'ignore'), u).encode()
            save(u, d)
        except Exception: pass
    def asset(u):  # картинки, стили и скрипты страницы качаются параллельно
        with slk:
            if u in seen or job['cancel']: return
            seen.add(u)
        futs.append(apool.submit(_asset, u))
    def vtarget(a):
        if a not in vloc:
            vloc[a] = None
            try:
                if a.split('?')[0].lower().endswith(('.m3u8', '.mpd')):
                    ps = grab(job, a, out, vids); vloc[a] = ps[0] if ps else None
                else: stream(job, a, lp(a), tot, t0); vloc[a] = lp(a)
            except Exception: pass
        return vloc[a]
    while pages and n < cap and not job['cancel']:
        u, d = pages.pop(0)
        if u in seen: continue
        seen.add(u)
        try: data, t = fetch(u)
        except Exception: continue
        if 'html' not in t: save(u, data); continue
        n += 1; job['title'] = f'{h}: страниц {n} из {cap}'; job['pct'] = min(99, n * 100 // cap); cur = lp(u); html = data.decode('utf-8', 'ignore')
        if first is None:
            first = cur; m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I); title = (m and m.group(1).strip()) or h
            # обложка: og:image, иначе первая картинка страницы (слева на странице тайтла)
            cm = (re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\'](.*?)["\']', html, re.I)
                  or re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:image["\']', html, re.I)
                  or re.search(r'<img\b[^>]*?\bsrc=["\'](.*?)["\']', html, re.I))
            if cm:
                try:
                    ca = urljoin(u, cm.group(1)); cd, ct = fetch(ca); cp = out / ('_cover' + (Path(urlparse(ca).path).suffix or '.jpg'))
                    if 'image' in ct: cp.parent.mkdir(parents=True, exist_ok=True); cp.write_bytes(cd); cover = str(cp)
                except Exception: pass
        def sub(m):
            tag, val = m.group(1).lower(), m.group(3)
            if val.startswith(('#', 'data:', 'mailto:', 'javascript:')) or tag == 'iframe': return m.group(0)
            a = urljoin(u, val).split('#')[0]
            if not a.startswith('http'): return m.group(0)
            if a.split('?')[0].lower().endswith(VEXT):
                t_ = vtarget(a) if job.get('videos', True) else None
                return m.group(0).replace(val, relp(t_, cur)) if t_ else m.group(0)
            if tag == 'a':
                if sel: return m.group(0).replace(val, rel(a, cur)) if a in qd else m.group(0)
                if urlparse(a).netloc != h or d >= job['depth'] or SKIP.search(a): return m.group(0)
                if a not in qd:
                    if len(qd) >= cap: lim[0] = True; return m.group(0)
                    qd.add(a); pages.append((a, d + 1))
            else: asset(a)
            return m.group(0).replace(val, rel(a, cur))
        html = re.sub(r'<(\w+)\b[^>]*?\b(?:src|href)=(["\'])(.*?)\2', sub, html)
        if job.get('videos', True):  # встроенные плееры (iframe) -> локальный <video>
            def fr(m):
                a = urljoin(u, m.group(2))
                if not VH.search(a): return m.group(0)
                return ''.join('<video controls preload="metadata" style="max-width:100%%" src="%s"></video>' % relp(p, cur) for p in grab(job, a, out, vids)) or m.group(0)
            html = re.sub(r'<iframe\b[^>]*?\bsrc=(["\'])(.*?)\1[^>]*>(?:\s*</iframe>)?', fr, html, flags=re.I | re.S)
        save(u, html.encode())
    while futs: futs.pop().result()
    apool.shutdown()
    if first:
        add(title, h, job['topic'] or 'Сайты', 'site', first, start, out, cover)
        if lim[0]: job['final'] = f'сохранено частично: достигнут лимит ({cap} стр.)'

def discover(tok, d):  # быстрый обход для визуального выбора страниц (только HTML, без картинок и видео)
    p = prev[tok]; start = d['urls'].split()[0]; h = urlparse(start).netloc; seen, level = {start}, [start]
    def get(u):
        try:
            data, t = fetch(u)
            if 'html' not in t: return u, None, []
            html = data.decode('utf-8', 'ignore'); m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
            ls = [urljoin(u, x).split('#')[0] for x in re.findall(r'<a\b[^>]*?\bhref=["\'](.*?)["\']', html, re.I)]
            return u, (m.group(1).strip() if m else u), [x for x in ls if x.startswith('http') and urlparse(x).netloc == h and not SKIP.search(x)]
        except Exception: return u, None, []
    for dep in range(int(d.get('depth', cfg['depth'])) + 1):
        nxt = []
        with ThreadPoolExecutor(6) as ex:
            for u, t, ls in ex.map(get, level):
                if t is None or len(p['pages']) >= 500: continue
                p['pages'].append({'url': u, 'title': t, 'depth': dep}); p['done'] = p['total'] = len(p['pages'])
                for x in ls:
                    if x not in seen: seen.add(x); nxt.append(x)
        level = nxt
        if not level or len(p['pages']) >= 500: break
    p['finished'] = True

# ---------- манга Senkuro: приём глав от закладки в браузере, загрузка страниц, читалка ----------
MH = ('shiro.senkuro.net', 'mirai.senkuro.net'); mlock = threading.Lock()
def sniff(b): return cover_cache.image_extension(b)
def orig(u):  # ссылка shiro содержит адрес оригинала на mirai
    try:
        t = urlparse(u).path.rsplit('/', 1)[-1].split('.')[0]; o = base64.urlsafe_b64decode(t + '=' * (-len(t) % 4)).decode()
        return o if urlparse(o).hostname == 'mirai.senkuro.net' else ''
    except Exception: return ''
def img(u):  # через закладку: сначала оригинал, иначе то, что показал сайт
    for x in [orig(u), u]:
        if not x: continue
        try:
            guard(x)
            with opener().open(urllib.request.Request(x, headers={**UA, 'Referer': 'https://senkuro.me/'}), timeout=30) as r: d = r.read()
            if sniff(d): return d
        except Exception: pass
_sl = threading.Lock()
def speed_add(job, nb):  # скорость за последние 5 секунд для карточки загрузки
    now = time.time()
    with _sl:
        w = job.setdefault('_w', []); w.append((now, nb))
        while w and now - w[0][0] > 5: w.pop(0)
        job['speed'] = sum(x[1] for x in w) / max(1.0, now - w[0][0]); job['_ts'] = now
class Fast:  # параллельные скачивания картинок: соединения переиспользуются, cookie и User-Agent берутся у браузера
    def __init__(self, ua, cookies): self.ua, self.ck, self.loc = ua, cookies, threading.local()
    def get(self, u):
        for x in [orig(u), u]:
            p = urlparse(x or '')
            if not x or not (p.hostname == urlparse(SITE).hostname or (p.hostname or '').endswith('.senkuro.net')): continue
            hdr = {'User-Agent': self.ua, 'Referer': SITE + '/', 'Accept': 'image/*,*/*', 'Cookie': '; '.join(f"{c['name']}={c['value']}" for c in self.ck if p.hostname.endswith(c['domain'].lstrip('.')))}
            if not hdr['Cookie']: del hdr['Cookie']
            d = self.loc.__dict__.setdefault('d', {}); k = (p.scheme, p.netloc)
            for _ in range(2):
                try:
                    if k not in d: d[k] = (http.client.HTTPSConnection if p.scheme == 'https' else http.client.HTTPConnection)(p.netloc, timeout=30)
                    d[k].request('GET', p.path + ('?' + p.query if p.query else ''), headers=hdr); r = d[k].getresponse(); b = r.read()
                    if r.status == 200 and sniff(b): return b
                    break
                except Exception:
                    try: d.pop(k).close()
                    except Exception: pass
def manga_chapter(job, d, get, tick=None, workers=1):  # качает страницы главы (workers>1 — параллельно), обновляет manifest и библиотеку
    folder = root('Manga') / safe(d['title'])[:60]; folder.mkdir(parents=True, exist_ok=True); mf = folder / 'manifest.json'; cover = ''; files = []; pages = d.get('pages') or []; n = len(pages)
    if d.get('cover'):
        b = get(d['cover'])
        if b: cp = folder / ('cover.' + sniff(b)); cp.write_bytes(b); cover = str(cp)
    if n:
        cd = folder / 'chapters' / d['cid']; cd.mkdir(parents=True, exist_ok=True); todo = []
        for i, u in enumerate(pages, 1):
            ex = next(cd.glob(f'{i:03d}.*'), None)
            if ex: files.append(ex.name)
            else: todo.append((i, u))
        def one(t):
            i, u = t
            if job['cancel']: return None
            b = get(u)
            if not b: return None
            fn = f'{i:03d}.{sniff(b)}'; (cd / fn).write_bytes(b); speed_add(job, len(b)); return fn
        pool = ThreadPoolExecutor(workers) if workers > 1 else None; k = n - len(todo)
        try:
            for fn in (pool.map(one, todo) if pool else map(one, todo)):
                k += 1
                if fn: files.append(fn)
                if tick: tick(k, n)
                else: job['title'] = f"{d['title']}: {d['label']} {k}/{n}"; job['pct'] = k * 100 // n
        finally:
            if pool: pool.shutdown()
        files.sort()
    with mlock:
        man = json.loads(mf.read_text('utf-8')) if mf.exists() else {'slug': d['slug'], 'title': d['title'], 'cover': '', 'chapters': {}}
        if n and files: man['chapters'][d['cid']] = {'label': d['label'], 'expected': d.get('expected') or n, 'files': files, 'done': len(files) == n == (d.get('expected') or n)}
        if d.get('listed'): man['listed'] = d['listed']
        if cover: man['cover'] = cover
        elif not man['cover'] and files: man['cover'] = str(folder / 'chapters' / d['cid'] / files[0])  # запасная обложка, пока нет настоящей
        mf.write_text(json.dumps(man, ensure_ascii=False), 'utf-8')
        add(d['title'], 'Senkuro', 'Манга', 'manga', folder, 'manga:' + d['slug'], folder, man['cover'])
    ok = len(files) == n
    if n and not ok and not tick: job['final'] = f"частично: {len(files)} из {n} стр."
    return ok
def manga(job): manga_chapter(job, job['m'], img)  # приём от закладки (запасной способ)

def pw_get(ctx):  # запасной путь: скачивание средствами браузера (те же cookie и заголовки, что у сайта)
    def get(u):
        for x in [orig(u), u]:
            if not x: continue
            try:
                r = ctx.request.get(x, headers={'Referer': SITE + '/'}, timeout=30000)
                if r.ok:
                    b = r.body()
                    if sniff(b): return b
            except Exception: pass
    return get
TMO = 45000; TRIES = 2; ADS = re.compile(r'yandex\.|doubleclick|googlesyndication|googletagmanager|google-analytics|adfox', re.I)
SRC_OK = "()=>{const i=document.querySelector('.reader-item img');return !!i&&/^https?:/.test(i.src)}"
def pw_pages(pg, url, st):  # адреса всех страниц главы; режимы «Лента» и «По страницам»
    pg.goto(url, wait_until='domcontentloaded'); pg.wait_for_selector('.reader-item img', timeout=TMO)
    if pg.locator('.reader-main-vertical').count():  # быстрая прокрутка к первой ещё не загруженной странице
        pg.evaluate("""async()=>{const ok=()=>[...document.querySelectorAll('.reader-item img')].every(i=>/^https?:/.test(i.src));
          for(let k=0;k<400&&!ok();k++){for(const e of document.querySelectorAll('.reader-item')){if(!/^https?:/.test(e.querySelector('img').src)){e.scrollIntoView();break}}await new Promise(r=>setTimeout(r,80))}}""")
        pg.wait_for_function("()=>[...document.querySelectorAll('.reader-item img')].every(i=>/^https?:/.test(i.src))", timeout=TMO)
        return pg.eval_on_selector_all('.reader-item img', 'els=>els.map(i=>i.src)')
    m = re.search(r'/\s*(\d+)', pg.locator('.nav-panel__page span').first.inner_text()); total = int(m.group(1)) if m else 1
    pg.wait_for_function(SRC_OK, timeout=TMO); out = [pg.eval_on_selector('.reader-item img', 'i=>i.src')]
    for k in range(2, total + 1):
        try:  # листаем кликом без перезагрузки страницы; если не вышло — переходом по адресу (и больше клик не пробуем)
            if st.get('noclick'): raise RuntimeError('клик отключён')
            pg.click('.tap-zone__next', timeout=1500)
            pg.wait_for_function("p=>{const i=document.querySelector('.reader-item img');return !!i&&/^https?:/.test(i.src)&&i.src!==p}", arg=out[-1], timeout=6000)
        except Exception:
            st['noclick'] = True
            pg.goto(re.sub(r'/pages/\d+', f'/pages/{k}', url), wait_until='domcontentloaded'); pg.wait_for_function(SRC_OK, timeout=TMO)
        out.append(pg.eval_on_selector('.reader-item img', 'i=>i.src'))
    if len(set(out)) != len(out): raise RuntimeError('страницы не сменились (одинаковые картинки)')
    return out

SITE = os.environ.get('MEDIAHUB_SITE', 'https://senkuro.me')
def chapter_done(folder, cid):
    try: return bool(json.loads((folder / 'manifest.json').read_text('utf-8'))['chapters'].get(cid, {}).get('done'))
    except Exception: return False
def joblog(folder, text):
    try:
        with open(folder / 'download.log', 'a', encoding='utf-8') as f: f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
    except Exception: pass
def manga_site(job):  # ссылка на тайтл -> сами открываем сайт в Edge/Chrome; страницы качаются параллельно, пока браузер листает следующую главу
    try: from playwright.sync_api import sync_playwright
    except ImportError: raise RuntimeError('нужен playwright: запустите start.bat ещё раз')
    mt = re.match(re.escape(SITE).replace('://', '://(?:www\\.)?', 1) + r'/manga/([a-z0-9-]+)', job['url'])
    if not mt: raise RuntimeError('ссылка должна вести на тайтл на senkuro.me')
    slug = mt.group(1); bad = {}; okn = [0]; N = 0; warn = ''
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(BASE / 'browser_profile'), headless=not cfg.get('show_browser'), viewport={'width': 1100, 'height': 900}, **({} if cfg.get('browser') in ('', 'chromium') else {'channel': cfg.get('browser') or 'msedge'}))
        try:
            ck = browser_cookies(urlparse(SITE).hostname or 'senkuro.me')
            if ck: ctx.add_cookies(ck)
        except Exception as e: warn = f' Cookie из браузера не взяты: {str(e)[:160]}'
        blk = [True]
        def block(route):  # картинки и реклама браузеру не нужны: адреса страниц берём из разметки, сами картинки качаем отдельно
            r = route.request
            if blk[0] and (r.resource_type in ('image', 'media', 'font') or ADS.search(urlparse(r.url).hostname or '')): return route.abort()
            route.continue_()
        ctx.route('**/*', block); pool = ThreadPoolExecutor(3)
        try:
            pg = ctx.new_page(); job['title'] = 'открываю страницу тайтла…'
            pg.goto(f'{SITE}/manga/{slug}/chapters', wait_until='domcontentloaded')
            try: pg.wait_for_selector('article.card-chapter', timeout=TMO)
            except Exception: raise RuntimeError('список глав не открылся (капча или блокировка?). Включите в настройках «Показывать окно браузера» и повторите')
            exp = 0
            try: mm = re.search(r'Главы\s+(\d+)', pg.inner_text('body')); exp = int(mm.group(1)) if mm else 0
            except Exception: pass
            last, calm = -1, 0
            for _ in range(80):  # список глав подгружается постепенно: ждём, пока он перестанет расти
                c = pg.locator('article.card-chapter').count(); job['title'] = f'ищу главы… найдено {c}' + (f' из {exp}' if exp else '')
                calm = calm + 1 if c == last else 0; last = c
                if calm >= (2 if exp and c >= exp else 6) or job['cancel']: break
                try: pg.locator('article.card-chapter').last.scroll_into_view_if_needed(timeout=2000)
                except Exception: pass
                pg.keyboard.press('End'); pg.mouse.wheel(0, 30000)
                try: pg.get_by_role('button', name=re.compile(r'^(показать|загрузить)\s+ещ[её]', re.I)).first.click(timeout=500)
                except Exception: pass
                pg.wait_for_timeout(900)
            title = pg.locator('h1').first.inner_text().strip() or slug; po = pg.locator('.project-poster img').first
            cover = urljoin(pg.url, po.get_attribute('data-zoom-src') or po.get_attribute('src') or '') if po.count() else ''
            chs = pg.eval_on_selector_all('article.card-chapter', "els=>els.map(a=>({url:(a.querySelector('a.card-chapter__link')||a.querySelector('a')).href,label:((a.querySelector('.card-chapter__name')||a).textContent||'').trim()}))")
            for c in chs: mm = re.search(r'chapters/(\d+)', c['url']); c['cid'] = mm.group(1) if mm else ''
            chs = [c for c in chs if c['cid']][::-1]  # от первой главы к последней
            if not chs: raise RuntimeError('главы не найдены')
            if exp and len(chs) < exp - 1: warn = f' Найдено глав {len(chs)}, а на сайте указано {exp}: повторите загрузку.'
            slow = pw_get(ctx); fast = Fast(pg.evaluate('navigator.userAgent'), ctx.cookies()); folder = root('Manga') / safe(title)[:60]
            manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': cover, 'listed': [{'cid': c['cid'], 'label': c['label']} for c in chs]}, slow)
            pst = {}; sel = chs[(job.get('first') or 1) - 1:(job.get('last') or len(chs))]; N = len(sel); pending, retry, fin, t0 = [], [], [0], time.time(); noop = lambda k, n: None
            def reap(keep):  # забираем завершённые скачивания; keep — сколько можно оставить в работе
                while pending and (len(pending) > keep or pending[0][0].done()):
                    f, c, d = pending.pop(0)
                    try: ok = f.result()
                    except Exception: ok = False
                    if ok: okn[0] += 1; fin[0] += 1; joblog(folder, c['label'] + ': ok')
                    else: retry.append((c, d))
                job['pct'] = min(99, int((fin[0] + len(retry)) * 100 / N))
            for i, c in enumerate(sel, 1):
                if job['cancel']: break
                job['title'] = f"{title} · глава {i}/{N} · {c['label']}" + (f' · качается {len(pending)}' if pending else ''); job['eta'] = int((time.time() - t0) / i * (N - i))
                if chapter_done(folder, c['cid']): okn[0] += 1; fin[0] += 1; continue  # уже скачана раньше
                err, pages = '', None
                for att in range(TRIES):
                    blk[0] = att == 0  # вторая попытка — без блокировки картинок
                    try: pages = pw_pages(pg, c['url'], pst); break
                    except Exception as e: err = (str(e).splitlines() or [repr(e)])[0][:160]
                blk[0] = True
                if not pages: bad[c['label']] = err; fin[0] += 1; joblog(folder, f"{c['label']}: {err}"); continue
                d = {'slug': slug, 'cid': c['cid'], 'title': title, 'label': c['label'], 'expected': len(pages), 'pages': pages}
                pending.append((pool.submit(manga_chapter, job, d, fast.get, noop, 8), c, d)); reap(2)
            reap(0)
            for c, d in retry:  # запасной проход: недокачанное берём средствами браузера
                if job['cancel']: break
                job['title'] = f"{title} · повторная загрузка · {c['label']}"
                if manga_chapter(job, d, slow, noop): okn[0] += 1; joblog(folder, c['label'] + ': ok (повтор)')
                else: bad[c['label']] = 'не все страницы скачались'; joblog(folder, c['label'] + ': не все страницы скачались')
        finally:
            pool.shutdown(); ctx.close()
    job['final'] = (f'готово: {okn[0]} из {N} глав.' if not bad else f'частично: {okn[0]} из {N} глав. Не удалось: ' + '; '.join(f'{k} ({v})' for k, v in list(bad.items())[:3])) + warn

_gs = {}
def games_server():  # GameSweep живёт внутри MediaHub; после каждого сканирования игры попадают в библиотеку
    if 'h' not in _gs:
        httpd = gamesweep.make_server(cfg.get('games_root', ''), 0); httpd.store.on_done = sync_games; httpd.store.layout = cfg.get('games_layout') if cfg.get('games_layout') in game_scan.LAYOUTS else 'auto'
        threading.Thread(target=httpd.serve_forever, daemon=True).start(); _gs['h'] = httpd
    return _gs['h']
def games_url(): h = games_server(); return f"http://127.0.0.1:{h.server_address[1]}/?t={h.token}"
def games_scan(root):
    if root and os.path.isdir(root): games_server().store.start_scan(root, cfg.get('games_layout') if cfg.get('games_layout') in game_scan.LAYOUTS else 'auto')
def plural(n, f): return f'{n} ' + (f[0] if n % 10 == 1 and n % 100 != 11 else f[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else f[2])
def sync_games(games, root):  # установленные игры: сливаем с карточками из браузера (по названию), остальные добавляем
    root = os.path.abspath(root); buckets = {}; cache = os.path.normcase(os.path.abspath(os.path.join(cfg['folder'], 'covers'))); games = [g for g in games if os.path.normcase(os.path.abspath(g['path'])) != cache]
    for g in games:
        pn = gamesweep.parse_name(g['name']); buckets.setdefault(pn['key'] or g['name'].casefold(), []).append((g, pn))
    groups = {gr['key']: gr for gr in gamesweep.build_groups(games)}
    for key, ms in buckets.items():
        gr = groups.get(key); keep = next((r for r in gr['members'] if r['status'] == 'оставить'), None) if gr else None
        newest = next((g for g, _ in ms if keep and g['path'] == keep['path']), None) or max((g for g, _ in ms), key=lambda g: g.get('mtime') or 0)
        pn = next(p for g, p in ms if g is newest); title = (gr['title'] if gr else ms[0][1]['base']) or ms[0][0]['name']; old = sum(1 for r in (gr['members'] if gr else []) if r['status'] in ('старая', 'дубль'))
        inst = {'version': (keep or {}).get('version') or (pn.get('text') or ''), 'versions': len(ms), 'old': old, 'root': root, 'path': newest['path']}
        row = find_game(key, title); info = ginfo(row) if row else {}; info['inst'] = inst; info.setdefault('added', time.time()); info.setdefault('auto', True)
        mv = info.get('meta', {}).get('version', ''); info['update'] = bool(mv and inst['version'] and gamelib.newer(mv, inst['version'])); cover = ''
        if not (row and row['thumb'] and Path(row['thumb']).is_file()):
            try: cover = cover_cache.cache_local_cover(newest['path'], cfg['folder'])
            except (OSError, ValueError) as e: logging.warning('Не удалось сохранить обложку %s: %s', title, e)
        if row:
            sql("update items set path=?, size=?, info=?, thumb=case when coalesce(thumb,'')=? and ?!='' then ? else thumb end where id=?", (newest['path'], int(newest.get('size') or 0), json.dumps(info, ensure_ascii=False), row['thumb'] or '', cover, cover, row['id']))
        else:
            sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)", (title, Path(root).name or 'Игры', 'Игры', 'game', newest['path'], '', 'game:' + key, int(newest.get('size') or 0), cover, root, json.dumps(info, ensure_ascii=False)))
    # A different layout or incomplete scan is not evidence that unseen cards should be deleted.
def manga_extra(r):
    if r['kind'] == 'game':
        g = game_view(r); return ' · '.join(x for x in [g['version'] or (g['latest'] if not g['downloaded'] else ''), ('старых ' + str(g['old'])) if g['old'] else ''] if x)
    if r['kind'] != 'manga': return ''
    try: m = json.loads((Path(r['root']) / 'manifest.json').read_text('utf-8')); return f"{len(m['chapters'])} из {len(m.get('listed', [])) or '?'} гл."
    except Exception: return ''

def manga_info(i):
    r = sql('select * from items where id=? and kind=?', (i, 'manga'))
    if not r: return {'error': 'not found'}
    man = json.loads((Path(r[0]['root']) / 'manifest.json').read_text('utf-8')); pr = sql('select cid,page from progress where slug=?', (man['slug'],))
    allc = {c['cid']: {'id': c['cid'], 'label': c['label'], 'files': [], 'expected': 0, 'done': False} for c in man.get('listed', [])}
    for k, v in man['chapters'].items(): allc[k] = dict(v, id=k)
    chs = sorted(allc.values(), key=lambda c: [float(x) for x in re.findall(r'\d+(?:\.\d+)?', c['label'])] or [0])
    return {'title': man['title'], 'chapters': chs, 'total': len(man.get('listed', [])), 'have': len(man['chapters']), 'progress': dict(pr[0]) if pr else None}

# ---------- оценка размера ----------
def preview(tok, d):
    import yt_dlp
    p = prev[tok]; kind = d['kind']
    if kind in ('site', 'mangaurl'): p['err'].append('Для сайтов размер заранее неизвестен'); p['finished'] = True; return
    o = base(); o.update(format=fmt(kind, d.get('res') or cfg['res']), extract_flat='in_playlist', ignoreerrors=True, skip_download=True)
    af = BASE / f'archive_{kind}.txt'; arch = set(af.read_text('utf-8').splitlines()) if cfg['skip'] and af.exists() else set()
    def size(i):
        return int(sum(f.get('filesize') or f.get('filesize_approx') or (f.get('tbr') or 0) * 125 * (i.get('duration') or 0) for f in (i.get('requested_formats') or [i])))
    def one(e):
        if (str(e.get('ie_key') or e.get('extractor_key') or '').lower() + ' ' + str(e.get('id'))) in arch: return -1
        try:
            if e.get('formats') or e.get('requested_formats'): return size(e)
            with yt_dlp.YoutubeDL(dict(o, extract_flat=False, noplaylist=True)) as y: return size(y.extract_info(e.get('url') or e.get('webpage_url'), download=False))
        except Exception: return 0
    for u in [x.strip() for x in d['urls'].splitlines() if x.strip().startswith('http')]:
        try:
            with yt_dlp.YoutubeDL(o) as y: t = y.extract_info(u, download=False)
            ents = [e for e in t['entries'] if e] if t.get('_type') == 'playlist' else [t]
        except Exception as ex: p['err'].append(str(ex)[:100]); continue
        p['total'] += len(ents)
        with ThreadPoolExecutor(4) as ex:
            for s in ex.map(one, ents):
                p['done'] += 1
                if s < 0: p['skipped'] += 1
                elif s == 0: p['unknown'] += 1
                else: p['size'] += s
    p['finished'] = True

# ---------- очередь / расписание ----------
def run_job(j):
    return ({'site': crawl, 'manga': manga, 'mangaurl': manga_site, 'mangabrowser': manga_browser, 'gamecard': game_card, 'gamecheck': game_check}.get(j['kind'], media))(j)
scheduler = JobQueue(jobs, ids, run_job)
enqueue, fire = scheduler.enqueue, scheduler.fire
def spawn_workers():
    cfg['workers'] = max(1, min(12, int(cfg.get('workers') or 3)))
    scheduler.spawn_workers(cfg['workers'])
# ---------- расширение браузера: входящие вкладки ----------
for c_ in ('src', 'tracked int default 0', 'checked', 'info'):
    try: db.execute('alter table items add column ' + c_)
    except sqlite3.OperationalError: pass
db.execute("create table if not exists inbox(id integer primary key, batch text, tab_id int, window_id int, url text, title text, kind text, host text, action text, state text, lib_id int, close_tab int, status text, reason text default '', jobs text default '[]', cmd text default '', created text default current_timestamp)")
EXTF = BASE / 'ext.json'
try: EXT = json.loads(EXTF.read_text('utf-8'))  # подключённые расширения: {origin: токен}
except Exception: EXT = {}
PAIR = {}  # запросы на подключение, ждущие решения человека
def ext_save(): EXTF.write_text(json.dumps(EXT, ensure_ascii=False), 'utf-8')
ACT = {'manga': ['download', 'track', 'link', 'skip'], 'video': ['download', 'link', 'skip'], 'playlist': ['download', 'track', 'link', 'skip'], 'audio': ['download', 'link', 'skip'],
       'podcast': ['link', 'track', 'skip'], 'game': ['gamecard', 'link', 'skip'], 'unknown': ['link', 'site', 'skip']}
DEFAULT = {'manga': 'download', 'video': 'download', 'playlist': 'download', 'audio': 'download', 'podcast': 'link', 'game': 'link', 'unknown': 'link'}
JOBK = {'manga': 'mangaurl', 'video': 'video', 'playlist': 'video', 'audio': 'audio', 'unknown': 'site'}
def new_job(url, kind, **kw):
    j = {'id': next(ids), 'url': url, 'kind': kind, 'res': cfg['res'], 'afmt': cfg['afmt'], 'depth': int(cfg['depth']), 'maxp': int(cfg['maxp']), 'videos': bool(cfg['videos']), 'sel': [], 'first': 0, 'last': 0,
         'topic': '', 'subs': cfg['subs_langs'] if cfg['subs_on'] else '', 'thumbs': bool(cfg['thumbs']), 'start_at': 0.0, 'daily': False, 'status': 'в очереди', 'pct': 0, 'title': url, 'speed': 0, 'eta': 0, 'cancel': False}
    j.update(kw); enqueue(j); return j['id']
def add_link(title, key, src, host, tracked=0):  # сохраняем источник
    sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,tracked) values(?,?,?,?,?,?,?,?,?,?,?) on conflict(url) do update set src=excluded.src, tracked=max(coalesce(items.tracked,0), excluded.tracked)",
        (title or key, host, 'Ссылки', 'link', '', '', key, 0, '', src, tracked))
def inbox_add(tabs, close, browser):
    batch = time.strftime('%Y%m%d%H%M%S') + '-' + str(next(ids)); seen = set(); n = 0
    for t in tabs[:200]:
        url = str(t.get('url') or '')[:2000]
        if not url.startswith(('http://', 'https://')): continue
        c = classify(url); key = c['key']; state, lib, action = 'new', None, ('gamecard' if c['host'] == 'f95zone.to' else DEFAULT[c['kind']])
        if key in seen: state, action = 'dup', 'skip'
        else:
            seen.add(key); it = sql("select * from items where url=? or (kind='game' and src=?)", (key, key))
            if it:
                it = it[0]; lib = it['id']
                if it['kind'] == 'game': state = 'downloaded' if (it['path'] and Path(it['path']).exists()) else 'card'; action = 'known'
                elif it['kind'] == 'link': state = 'link'
                elif it['path'] and not Path(it['path']).exists(): state = 'missing'
                else: state = 'downloaded'; action = 'known' if c['kind'] != 'playlist' else action
        sql('insert into inbox(batch,tab_id,window_id,url,title,kind,host,action,state,lib_id,close_tab,status) values(?,?,?,?,?,?,?,?,?,?,?,?)',
            (batch, t.get('id'), t.get('windowId'), url, str(t.get('title') or url)[:300], c['kind'], c['host'], action, state, lib, 1 if close else 0, 'pending')); n += 1
    return batch, n
def finish_row(rid, close): sql('update inbox set status=?, cmd=? where id=?', ('closing', 'close', rid) if close else ('done', '', rid))
@inbox_lock.serialize_confirm
def inbox_confirm(d):  # подтверждение не атомарно
    rows = {r['id']: r for r in sql('select * from inbox where batch=?', (d['batch'],))}; close = bool(d.get('close')); nd = nl = 0
    for x in d.get('rows', []):
        r = rows.pop(x.get('id'), None)
        if not r or r['status'] != 'pending': continue
        kind = x.get('kind') if x.get('kind') in ACT else r['kind']; a = x.get('action'); a = a if (a in ACT[kind] or (a == 'known' and r['state'] in ('downloaded', 'card'))) else 'skip'
        sql('update inbox set kind=?, action=?, close_tab=? where id=?', (kind, a, 1 if close else 0, r['id']))
        if a == 'skip': sql("update inbox set status='skipped' where id=?", (r['id'],)); continue
        if a == 'known': finish_row(r['id'], close); continue
        c = classify(r['url'])
        if a == 'gamecard':
            jid = new_job(c['key'] or r['url'], 'gamecard', title=r['title']); sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), r['id'])); nd += 1; continue
        add_link(r['title'], c['key'], r['url'], r['host'], 1 if (a == 'track' or (kind == 'playlist' and a == 'download')) else 0)
        if a in ('link', 'track'): finish_row(r['id'], close); nl += 1; continue
        jk = 'site' if a == 'site' else JOBK.get(kind)
        if jk == 'mangaurl': jk = manga_kind()
        if not jk: sql("update inbox set status='kept', reason=? where id=?", ('скачивание с этого источника пока недоступно', r['id'])); continue
        jid = new_job(c.get('norm') or r['url'], jk, title=r['title']); sql("update inbox set status='queued', jobs=? where id=?", (json.dumps([jid]), r['id'])); nd += 1
    return {'download': nd, 'links': nl}
def settle():  # закрывать только после успеха
    for r in sql("select * from inbox where status='queued'"):
        js_ = json.loads(r['jobs'] or '[]'); sts = [jobs[j]['status'] for j in js_ if j in jobs]
        if not js_ or len(sts) < len(js_):  # после перезапуска нельзя подтвердить успешность отсутствующих заданий
            # Наличие файла не доказывает, что вся загрузка завершилась успешно.
            sts = ['ошибка: результат неизвестен после перезапуска, проверьте библиотеку']
        if any(re.match(r'(качается|в очереди|запл)', s) for s in sts): continue
        bad = next((s for s in sts if s.startswith('сохранено частично') or not s.startswith(('готово', 'сохранено'))), '')
        if not bad: finish_row(r['id'], r['close_tab']); continue
        low = bad.lower(); why = ('нужен вход на сайте' if re.search(r'login|sign in|private|authent|cookies|членам|вход', low) else 'скачано частично' if bad.startswith(('частично', 'сохранено частично')) else 'загрузка отменена' if bad.startswith('отменено') else 'загрузка пропущена, проверьте библиотеку' if bad.startswith('пропущено') else 'не удалось скачать (' + bad.replace('ошибка:', '').strip()[:120] + ')')
        sql("update inbox set status='kept', reason=? where id=?", (why, r['id']))
def settle_loop():
    while True:
        try: settle()
        except Exception: pass
        time.sleep(2)
def inbox_view(r):
    st = r['status']; act = r['action']
    st_txt = {'new': 'Новое', 'dup': 'Такая же вкладка уже есть в этом списке', 'link': 'Уже в библиотеке · только ссылка', 'missing': 'Уже в библиотеке · файл не найден', 'downloaded': 'Уже в библиотеке · скачано', 'card': 'Уже в библиотеке игр · не скачано'}.get(r['state'], '')
    fate = {'pending': 'Вкладка может закрыться после успешной обработки' if (r['close_tab'] and act != 'skip') else 'Вкладка останется открытой', 'queued': 'Задание в очереди или выполняется' + (', вкладка может закрыться после успеха' if r['close_tab'] else ''),
            'closing': 'Ожидается ответ браузера на запрос закрытия…', 'closed': 'Вкладка закрыта · источник сохранён в библиотеке', 'done': 'Готово · источник сохранён в библиотеке', 'skipped': 'Пропущено, вкладка осталась открытой',
            'reopened': 'Вкладка возвращена', 'kept': 'Вкладка осталась открытой: ' + (r['reason'] or '')}.get(st, '')
    return {'id': r['id'], 'title': r['title'], 'url': r['url'], 'host': r['host'], 'kind': r['kind'], 'action': act, 'actions': ACT.get(r['kind'], []) + (['known'] if r['state'] in ('downloaded', 'card') else []),
            'state': r['state'], 'state_text': st_txt, 'status': st, 'fate': fate, 'close': bool(r['close_tab'])}
def inbox_state():
    out = []
    for b in sql('select batch, min(created) c, count(*) n from inbox group by batch order by batch desc limit 8'):
        rows = sql('select * from inbox where batch=? order by id', (b['batch'],)); out.append({'batch': b['batch'], 'created': b['c'], 'rows': [inbox_view(r) for r in rows], 'pending': any(r['status'] == 'pending' for r in rows)})
    return {'batches': out}
# ---------- задания для расширения: манга в браузере пользователя ----------
XT, XTL, EXT_SEEN = {}, threading.Lock(), [0.0]
def ext_online(): return bool(EXT) and time.time() - EXT_SEEN[0] < 40
def manga_kind():  # где качать мангу: в браузере пользователя (расширение) или отдельным окном (Playwright)
    v = cfg.get('manga_via', 'auto'); return 'mangabrowser' if v == 'browser' or (v == 'auto' and ext_online()) else 'mangaurl'
def take_tasks():
    with XTL:
        out = []
        for tid, t in XT.items():
            if not t['sent']: t['sent'] = True; out.append({'id': tid, 'type': t['type'], 'payload': t['payload']})
        return out
def xtask(kind, payload, timeout=180, job=None):  # поставить задание расширению и дождаться ответа
    tid = next(ids); ev = threading.Event(); end = time.time() + timeout
    with XTL: XT[tid] = {'type': kind, 'payload': payload, 'ev': ev, 'res': None, 'sent': False}
    try:
        while not ev.wait(1):
            if job and job['cancel']: raise RuntimeError('отменено')
            if time.time() > end: raise RuntimeError('расширение не ответило: откройте браузер с расширением MediaHub и не закрывайте окно загрузки')
        r = XT[tid]['res']
    finally:
        with XTL: XT.pop(tid, None)
    if not r.get('ok'): raise RuntimeError(r.get('error') or 'расширение вернуло ошибку')
    return r.get('data') or {}
def firefox_cookies(domain):  # cookie Firefox читаются спокойно и при открытом браузере
    import glob, tempfile
    roots = [os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles'), os.path.expanduser('~/.mozilla/firefox'), os.path.expanduser('~/Library/Application Support/Firefox/Profiles'), os.path.expanduser('~/snap/firefox/common/.mozilla/firefox')]
    dbs = [p for r in roots for p in glob.glob(os.path.join(r, '*', 'cookies.sqlite'))]
    if not dbs: raise RuntimeError('профиль Firefox не найден')
    src, out = max(dbs, key=os.path.getmtime), []
    with tempfile.TemporaryDirectory() as t:
        for e_ in ('', '-wal', '-shm'):
            if os.path.exists(src + e_): shutil.copy(src + e_, os.path.join(t, 'c.sqlite' + e_))
        con = sqlite3.connect(os.path.join(t, 'c.sqlite'))
        for n, v, h, p, e, sec, ho, ss in con.execute('select name,value,host,path,expiry,isSecure,isHttpOnly,sameSite from moz_cookies where host like ?', ('%' + domain,)):
            exp = e / 1000.0 if e > 1e11 else float(e)
            out.append({'name': n, 'value': v, 'domain': h, 'path': p, 'expires': exp if exp > 0 else -1, 'secure': bool(sec), 'httpOnly': bool(ho), 'sameSite': {0: 'None', 1: 'Lax', 2: 'Strict'}.get(ss, 'Lax') if (ss != 0 or sec) else 'Lax'})
        con.close()
    return out
def browser_cookies(domain):  # cookie вашего браузера только для этого сайта (нужны для входа)
    b = (cfg.get('cookie_browser') or '').lower()
    if not b: return []
    if b == 'firefox': return firefox_cookies(domain)
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        jar = extract_cookies_from_browser(b)
    except Exception as e:
        raise RuntimeError(f'{b}: cookie недоступны (браузер шифрует их и блокирует базу, пока открыт; закройте {b} или скачивайте мангу через расширение). {str(e)[:90]}')
    return [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path or '/', 'secure': bool(c.secure), 'expires': float(c.expires) if c.expires else -1} for c in jar if domain in (c.domain or '')]
def manga_browser(job):  # те же шаги, что в manga_site, но сайт открывает расширение в браузере пользователя: его вход, его cookie
    mt = re.match(re.escape(SITE).replace('://', '://(?:www\\.)?', 1) + r'/manga/([a-z0-9-]+)', job['url'])
    if not mt: raise RuntimeError('ссылка должна вести на тайтл на senkuro.me')
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер (Яндекс, Firefox, Edge или Chrome) с установленным расширением')
    slug = mt.group(1); bad = {}; okn = [0]; N = 0; warn = ''; pool = ThreadPoolExecutor(3)
    try:
        job['title'] = 'открываю тайтл в вашем браузере…'
        d = xtask('manga_list', {'url': f'{SITE}/manga/{slug}/chapters', 'site': SITE}, 240, job)
        title = (d.get('title') or slug).strip(); exp = int(d.get('expected') or 0); chs = [c for c in d.get('chapters', []) if c.get('cid')][::-1]
        if not chs: raise RuntimeError('главы не найдены')
        if exp and len(chs) < exp - 1: warn = f' Найдено глав {len(chs)}, а на сайте указано {exp}: повторите загрузку.'
        fast = Fast(d.get('ua') or 'Mozilla/5.0', []); folder = root('Manga') / safe(title)[:60]
        manga_chapter(job, {'slug': slug, 'cid': '', 'title': title, 'label': '', 'pages': [], 'cover': d.get('cover') or '', 'listed': [{'cid': c['cid'], 'label': c['label']} for c in chs]}, fast.get)
        sel = chs[(job.get('first') or 1) - 1:(job.get('last') or len(chs))]; N = len(sel); pending, retry, fin, t0 = [], [], [0], time.time(); noop = lambda k, n: None
        def reap(keep):
            while pending and (len(pending) > keep or pending[0][0].done()):
                f, c, d2 = pending.pop(0)
                try: ok = f.result()
                except Exception: ok = False
                if ok: okn[0] += 1; fin[0] += 1; joblog(folder, c['label'] + ': ok')
                else: retry.append((c, d2))
            job['pct'] = min(99, int((fin[0] + len(retry)) * 100 / N))
        for i, c in enumerate(sel, 1):
            if job['cancel']: break
            job['title'] = f"{title} · глава {i}/{N} · {c['label']}" + (f' · качается {len(pending)}' if pending else ''); job['eta'] = int((time.time() - t0) / i * (N - i))
            if chapter_done(folder, c['cid']): okn[0] += 1; fin[0] += 1; continue
            err, pages = '', None
            for _ in range(TRIES):
                try:
                    r = xtask('manga_pages', {'url': c['url'], 'site': SITE}, 300, job); pages = r.get('pages') or []
                    if r.get('error') or not pages or (r.get('total') and len(pages) < int(r['total'])): raise RuntimeError(r.get('error') or f"страниц {len(pages)} из {r.get('total')}")
                    break
                except Exception as e: err = (str(e).splitlines() or [repr(e)])[0][:160]; pages = None
            if not pages: bad[c['label']] = err; fin[0] += 1; joblog(folder, f"{c['label']}: {err}"); continue
            d2 = {'slug': slug, 'cid': c['cid'], 'title': title, 'label': c['label'], 'expected': len(pages), 'pages': pages}
            pending.append((pool.submit(manga_chapter, job, d2, fast.get, noop, 8), c, d2)); reap(2)
        reap(0)
        for c, d2 in retry:
            if job['cancel']: break
            job['title'] = f"{title} · повторная загрузка · {c['label']}"
            if manga_chapter(job, d2, fast.get, noop): okn[0] += 1; joblog(folder, c['label'] + ': ok (повтор)')
            else: bad[c['label']] = 'не все страницы скачались'; joblog(folder, c['label'] + ': не все страницы скачались')
    finally:
        pool.shutdown()
        try: xtask('manga_done', {}, 20)
        except Exception: pass
    job['final'] = (f'готово: {okn[0]} из {N} глав.' if not bad else f'частично: {okn[0]} из {N} глав. Не удалось: ' + '; '.join(f'{k} ({v})' for k, v in list(bad.items())[:3])) + warn

# ---------- библиотека игр: карточка из страницы темы, версии, обновления ----------
def name_key(name):
    return gamesweep.parse_name(name)['key'] or re.sub(r'\W+', '', str(name).casefold())
def ginfo(r):
    try: return json.loads(r['info'] or '{}')
    except Exception: return {}
def ginfo_save(rid, info): sql('update items set info=? where id=?', (json.dumps(info, ensure_ascii=False), rid))
def find_game(key, title=''):  # сначала точный ключ, затем похожее название (папка и тема называются по-разному)
    r = sql("select * from items where kind='game' and url=?", ('game:' + key,))
    if r: return r[0]
    import difflib
    best, score = None, 0.0
    for x in sql("select * from items where kind='game'"):
        k = x['url'][5:] if str(x['url']).startswith('game:') else name_key(x['title'])
        if re.findall(r'\d+', k) != re.findall(r'\d+', key): continue  # разные номера
        s = difflib.SequenceMatcher(None, k, key).ratio()
        if s > score: best, score = x, s
    return best if score >= 0.9 else None
def game_view(r):  # всё, что нужно карточке в библиотеке
    i = ginfo(r); m = i.get('meta', {}); inst = i.get('inst', {}); dl = bool(r['path'] and Path(r['path']).exists())
    return {'downloaded': dl, 'version': inst.get('version', '') if dl else '', 'latest': m.get('version', ''), 'update': bool(i.get('update') and dl), 'genres': m.get('genres', []), 'developer': m.get('developer', ''),
            'engine': m.get('engine', ''), 'os': m.get('os', ''), 'status': m.get('status', ''), 'release': m.get('release', ''), 'desc': m.get('desc', ''), 'links': m.get('links', []), 'support': m.get('support', []), 'thread': m.get('thread') or '',
            'language': m.get('language', ''), 'auto': i.get('auto', True), 'note': i.get('note', ''), 'checked': i.get('checked', 0), 'added': i.get('added', 0), 'versions': inst.get('versions', 1 if dl else 0), 'old': inst.get('old', 0), 'path': r['path'] if dl else ''}
def fetch_cover(url, referer, key):
    data = cover_download.download_cover(url, referer, guard, opener(), cover_cache.MAX_COVER_BYTES)
    return cover_cache.cache_bytes(data, cfg['folder'])
def apply_meta(meta, thread):  # создаёт или обновляет карточку игры; установленные файлы не трогаем
    name = meta['name'] or thread; key = name_key(name); row = find_game(key, name); info = ginfo(row) if row else {}
    info['meta'] = dict(meta, thread=thread); info['checked'] = time.time(); info.setdefault('added', time.time()); info.setdefault('auto', True)
    inst = info.get('inst', {}).get('version', ''); info['update'] = bool(inst and gamelib.newer(meta.get('version', ''), inst))
    cover = ''
    if meta.get('cover') and not (row and row['thumb'] and Path(row['thumb']).is_file()):
        try: cover = fetch_cover(meta['cover'], thread, key)
        except Exception as e: logging.warning('Не удалось загрузить обложку %s: %s', name, e)
    if row:
        sql("update items set title=?, author=?, src=?, info=?, thumb=case when coalesce(thumb,'')=? and ?!='' then ? else thumb end where id=?", (name, meta.get('developer') or row['author'], thread, json.dumps(info, ensure_ascii=False), row['thumb'] or '', cover, cover, row['id']))
        return row['id']
    sql("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)", (name, meta.get('developer') or 'Игры', 'Игры', 'game', '', '', 'game:' + key, 0, cover, thread, json.dumps(info, ensure_ascii=False)))
    return sql("select id from items where url=?", ('game:' + key,))[0]['id']
def fetch_html(url, job=None):
    d = xtask('fetch_html', {'url': url, 'site': '{0.scheme}://{0.netloc}'.format(urlparse(url))}, 180, job); return d.get('html') or ''
def game_card(job):  # вкладка в браузере -> карточка игры
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер с установленным расширением')
    url = job['url']; job['title'] = 'читаю страницу игры в вашем браузере…'; meta = gamelib.parse_thread(fetch_html(url, job), url)
    if meta.get('blocked'): raise RuntimeError('сайт показал проверку Cloudflare вместо страницы: откройте сайт в этом браузере, пройдите проверку и повторите')
    if not meta['name']: raise RuntimeError('на странице не нашлось названия игры (нужен вход на сайт?)')
    apply_meta(meta, gamelib.thread_key(url)); job['title'] = 'Карточка: ' + meta['name']; job['final'] = f"готово: «{meta['name']}», версия {meta['version'] or 'не указана'}"
def game_check(job):  # проверка новых версий: по одной странице в вашем браузере, неторопливо
    if not ext_online(): raise RuntimeError('расширение MediaHub не на связи: откройте браузер с установленным расширением')
    ids = job.get('ids') or [r['id'] for r in sql("select * from items where kind='game'") if ginfo(r).get('meta', {}).get('thread')]
    delay = float(os.environ.get('MEDIAHUB_GAME_DELAY', cfg.get('games_delay') or 8)); n = upd = 0; bad = []
    for k, rid in enumerate(ids):
        if job['cancel']: break
        rows = sql('select * from items where id=?', (rid,))
        if not rows: continue
        r = rows[0]; i = ginfo(r); th = i.get('meta', {}).get('thread')
        if not th: continue
        job['title'] = f"Проверка игр {k + 1}/{len(ids)}: {r['title']}"; job['pct'] = int(k * 100 / max(1, len(ids)))
        try:
            meta = gamelib.parse_thread(fetch_html(th, job), th)
            if meta.get('blocked'): raise RuntimeError('проверка Cloudflare: пройдите её в браузере')
            if not meta['name']: raise RuntimeError('страница не открылась')
            old = i.get('meta', {}).get('version', ''); apply_meta(meta, th); n += 1
            if meta.get('version') and meta['version'] != old: upd += 1
        except Exception as e: bad.append(f"{r['title']}: {str(e)[:60]}")
        if k < len(ids) - 1 and delay: time.sleep(delay)
    job['final'] = f'готово: проверено {n}, изменилась версия у {upd}' + (f'. Не удалось: {len(bad)} ({bad[0]})' if bad else '')
def game_auto_loop():  # по расписанию (0 часов = выключено): проверяем игры с включённым «следить»
    while True:
        time.sleep(60)
        try:
            hrs = float(cfg.get('games_check_hours') or 0)
            if hrs > 0 and ext_online() and not any(j['kind'] == 'gamecheck' and j['status'].startswith(('качается', 'в очереди')) for j in jobs.values()):
                due = [r['id'] for r in sql("select * from items where kind='game'") if ginfo(r).get('meta', {}).get('thread') and ginfo(r).get('auto', True) and time.time() - ginfo(r).get('checked', 0) > hrs * 3600]
                if due: new_job('games:auto', 'gamecheck', ids=due[:20], title='Проверка игр по расписанию')
        except Exception: pass

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def js(self, o, code=200):
        b = json.dumps(o, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', len(b))
        if getattr(self, '_aco', ''): self.send_header('Access-Control-Allow-Origin', self._aco)
        self.end_headers(); self.wfile.write(b)
    def file(self, p):
        p = Path(p)
        if not p.is_file(): return self.send_error(404)
        with open(p, 'rb') as f:
            size = os.fstat(f.fileno()).st_size
            headers = self.headers.get_all('Range', []); choice = byte_range.select_range(headers[0], size) if len(headers) == 1 and 'If-Range' not in self.headers else None
            if choice is byte_range.UNSATISFIABLE:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.send_header('Content-Length', 0); self.send_header('Accept-Ranges', 'bytes'); self.end_headers(); return
            a, b = choice if choice is not None else (0, size - 1); f.seek(a)
            self.send_response(206 if choice is not None else 200)
            self.send_header('Content-Type', mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', b - a + 1)
            if choice is not None: self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
            self.end_headers(); left = b - a + 1
            while left > 0:
                c = f.read(min(1 << 20, left))
                if not c: break
                try: self.wfile.write(c)
                except OSError: return
                left -= len(c)
    def do_OPTIONS(self):
        if not self.host_ok(): return self.send_error(403)
        o = self.headers.get('Origin') or ''; allow = o if o.startswith(('chrome-extension://', 'moz-extension://')) else (o if o in ('https://senkuro.me', 'https://www.senkuro.me') else '')
        self.send_response(204)
        if allow:
            for k, v in {'Access-Control-Allow-Origin': allow, 'Access-Control-Allow-Methods': 'GET, POST', 'Access-Control-Allow-Headers': 'Content-Type, X-MH-Token', 'Access-Control-Allow-Private-Network': 'true', 'Access-Control-Max-Age': '600'}.items(): self.send_header(k, v)
        self.end_headers()
    def ext_origin(self):
        o = self.headers.get('Origin') or ''; return o if o.startswith(('chrome-extension://', 'moz-extension://')) else ''
    def ext_ok(self, o):  # доступ по секретному токену: Chrome не присылает Origin в GET-запросах расширения, поэтому к Origin не привязываемся
        t = self.headers.get('X-MH-Token') or ''; ok = bool(t) and any(hmac.compare_digest(v, t) for v in EXT.values())
        if ok: EXT_SEEN[0] = time.time()
        return ok
    def ext_get(self, p, qs):  # расширение опрашивает приложение: какие вкладки пора закрыть
        o = self.ext_origin(); self._aco = o or '*'
        if not self.ext_ok(o): return self.js({'error': 'auth'}, 401)
        if p == '/ext/commands':
            end = time.time() + min(25.0, float(qs.get('wait') or 0))
            while True:
                settle(); rows = sql("select * from inbox where cmd!=''"); tasks = take_tasks(); EXT_SEEN[0] = time.time()
                if rows or tasks or time.time() >= end: break
                time.sleep(0.5)
            return self.js({'commands': [{'id': r['id'], 'cmd': r['cmd'], 'tab_id': r['tab_id'], 'url': r['url'], 'title': r['title']} for r in rows] + [{'cmd': 'task', 'task': t['id'], 'type': t['type'], 'payload': t['payload']} for t in tasks]})
        if p == '/ext/ping': return self.js({'ok': 1})
        self.send_error(404)
    def ext_post(self):
        o = self.ext_origin(); self._aco = o or '*'; d = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 2_000_000)) or b'{}')
        if self.path == '/ext/hello':  # знакомство: токен выдаётся только после согласия человека в приложении
            if not o: return self.js({'error': 'origin'}, 403)
            if o in EXT: return self.js({'status': 'ok', 'token': EXT[o]})
            PAIR[o] = {'name': str(d.get('name') or 'Браузер')[:40], 't': time.time()}; return self.js({'status': 'pending'})
        if not self.ext_ok(o): return self.js({'error': 'auth'}, 401)
        if self.path == '/ext/game/add': return self.js(*quick_game_request(d, new_job))
        if self.path == '/ext/result':  # расширение вернуло результат задания (список глав, адреса страниц)
            with XTL: t = XT.get(d.get('id'))
            if t: t['res'] = {'ok': bool(d.get('ok')), 'data': d.get('data'), 'error': d.get('error')}; t['ev'].set()
            return self.js({'ok': 1})
        if self.path == '/ext/tabs':
            batch, n = inbox_add(d.get('tabs') or [], bool(d.get('close')), str(d.get('browser') or '')); return self.js({'batch': batch, 'count': n})
        if self.path == '/ext/ack':
            r = sql('select * from inbox where id=?', (d.get('id'),)); res = d.get('result')
            if r: sql('update inbox set cmd=?, status=?, reason=? where id=?', ('', 'closed' if res in ('closed', 'missing') else 'kept', {'cancelled': 'вы отменили закрытие', 'moved': 'вкладка уже открыта на другой странице', 'failed': 'браузер не дал закрыть вкладку'}.get(res, ''), r[0]['id']))
            return self.js({'ok': 1})
        self.send_error(404)
    def ingest(self):  # приём глав/обложки от закладки (только с senkuro.me)
        raw = self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 4_000_000)).decode('utf-8', 'ignore'); test = os.environ.get('MEDIAHUB_TEST_ALLOW_LOCAL') == '1'
        if self.headers.get('Origin') not in ('https://senkuro.me', 'https://www.senkuro.me') and not test: return self.send_error(403)
        try:
            if raw.startswith('data='): raw = parse_qs(raw)['data'][0]
            d = json.loads(raw); slug = str(d['slug']); cid = str(d.get('cid', ''))
            ok = lambda u: isinstance(u, str) and ((urlparse(u).hostname in MH and u.startswith('https://')) or test)
            assert re.fullmatch(r'[a-z0-9-]{1,300}', slug) and (not cid or re.fullmatch(r'\d{1,30}', cid))
            m = {'slug': slug, 'cid': cid, 'title': str(d['title'])[:200] or slug[:60], 'label': str(d.get('label', ''))[:80], 'expected': min(int(d.get('expected') or 0), 600),
                 'pages': [u for u in d.get('pages', [])[:600] if ok(u)], 'cover': d['cover'] if ok(d.get('cover')) else '',
                 'listed': [{'cid': str(c['cid']), 'label': str(c.get('label', ''))[:80]} for c in d.get('listed', [])[:2000] if isinstance(c, dict) and re.fullmatch(r'\d{1,30}', str(c.get('cid', '')))]}
            assert (m['pages'] and cid) or m['cover'] or m['listed']
        except Exception: return self.send_error(400)
        enqueue({'id': next(ids), 'url': 'manga:' + slug, 'kind': 'manga', 'm': m, 'topic': '', 'daily': False, 'start_at': 0, 'status': 'в очереди', 'pct': 0,
                 'title': (m['title'] + ' ' + m['label']).strip(), 'speed': 0, 'eta': 0, 'cancel': False})
        self.send_response(200); self.send_header('Access-Control-Allow-Origin', 'https://senkuro.me'); self.send_header('Content-Length', 2); self.end_headers(); self.wfile.write(b'ok')
    def host_ok(self): return (self.headers.get('Host') or '').split(':')[0] in ('127.0.0.1', 'localhost')
    def do_GET(self):
        if not self.host_ok(): return self.send_error(403)
        try: self.get()
        except Exception as e: self.js({'error': str(e)}, 500)
    def get(self):
        u = urlparse(self.path); p = unquote(u.path); qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        if p.startswith(('/sub/', '/api/subtitles/', '/api/player-preview/')): return player_preview.get(self, p, sql) if p.startswith('/api/player-preview/') else media_subtitles.get(self, p, sql)
        if p == '/' or p in ('/ui/app.js', '/ui/inbox-submit.js', '/ui/preferences.js', '/ui/notifications.js', '/ui/hotkeys.js', '/ui/job-events.js', '/ui/cancel-all.js', '/ui/delete-dialog.js', '/ui/game-library.js', '/ui/game-scan-settings.js', '/ui/library-view.js', '/ui/game-tags.js', '/ui/game-update-preview.js', '/ui/save-inventory.js', '/ui/accessibility.css', '/ui/reader.js', '/ui/reader-images.js', '/ui/reader-progress.js', '/ui/reader-modes.js', '/ui/reader.css', '/ui/player.js', '/ui/player-keys.js', '/ui/player-subtitles.js', '/ui/player.css'): return self.file(ASSETS / ('ui/index.html' if p == '/' else p.lstrip('/')))
        if p == '/api/jobs':
            now = time.time(); keys = ('id', 'url', 'kind', 'status', 'pct', 'title', 'eta', 'daily', 'start_at')
            return self.js([dict({k: j.get(k) for k in keys}, speed=(j.get('speed') or 0) if now - j.get('_ts', now) < 8 else 0) for j in jobs.values()])
        if p.startswith('/ext/'): return self.ext_get(p, qs)
        if p == '/api/inbox': return self.js(inbox_state())
        if p == '/api/ext':
            for o in [o for o, v in PAIR.items() if time.time() - v['t'] > 150]: PAIR.pop(o, None)
            return self.js({'pending': [{'origin': o, 'name': v['name']} for o, v in PAIR.items()], 'paired': list(EXT), 'ext_dir': str(ASSETS / 'extension'), 'ext_ff': str(ASSETS / 'extension-firefox' / 'manifest.json'), 'inbox_pending': sql("select count(*) n from inbox where status='pending'")[0]['n']})
        if p == '/api/settings': return self.js(cfg)
        if p == '/api/games': return self.js({'url': games_url()})
        if p == '/api/disk': return self.js(dict(zip(('total', 'used', 'free'), shutil.disk_usage(root('Video')))))
        if p == '/api/preview':
            r = dict(prev[qs['t']]); r['pages'] = r.get('pages', [])[int(qs.get('from', 0)):]; r['free'] = shutil.disk_usage(root('Video')).free; return self.js(r)
        if p == '/api/library':
            out = []; tag_map = game_tags.all_tags(db, lock)
            for r in library_search.find(db, lock, qs.get('q', ''), qs.get('kind', '')):
                d = dict(r); d['missing'] = not Path(r['path']).exists(); d['cover'] = f"/t/{r['id']}" if r['thumb'] and (r['kind'] != 'game' or Path(r['thumb']).is_file()) else ''; d['extra'] = manga_extra(r)
                d['open'] = f"/s/{r['id']}/" + os.path.relpath(r['path'], r['root']).replace(os.sep, '/') if r['kind'] == 'site' else f"/m/{r['id']}" if r['kind'] == 'manga' else f"/f/{r['id']}"
                if r['kind'] == 'game': d['g'] = game_view(r); d['g']['tags'] = tag_map.get(r['id'], []); d['missing'] = False
                d['state'] = 'link' if r['kind'] == 'link' else ('missing' if d['missing'] else 'ok'); d['tracked'] = r['tracked'] or 0
                if r['kind'] == 'link': d['open'] = r['src'] or r['url']; d['missing'] = False
                out.append(d)
            return self.js(out)
        mm = re.fullmatch(r'/([mp])/\d+', p)
        if mm: return self.file(ASSETS / 'ui' / ('reader.html' if mm.group(1) == 'm' else 'player.html'))
        mm = re.match(r'/api/manga/(\d+)$', p)
        if mm: return self.js(manga_info(int(mm.group(1))))
        mm = re.match(r'/mi/(\d+)/(\d+)/(\d{3}\.\w+)$', p)
        if mm:
            r = sql('select * from items where id=? and kind=?', (mm.group(1), 'manga'))
            return self.file(Path(r[0]['root']) / 'chapters' / mm.group(2) / mm.group(3)) if r else self.send_error(404)
        m = re.match(r'/([fst])/(\d+)(?:/(.*))?$', p)
        if m:
            r = sql('select * from items where id=?', (m.group(2),))
            if not r: return self.send_error(404)
            if m.group(1) == 'f': return self.file(r[0]['path'])
            if m.group(1) == 't': return self.file(r[0]['thumb'] or '')
            t = (Path(r[0]['root']) / m.group(3)).resolve()
            return self.file(t) if Path(r[0]['root']).resolve() in t.parents else self.send_error(403)
        self.send_error(404)
    def do_POST(self):
        if not self.host_ok(): return self.send_error(403)
        if self.path != '/ingest' and not self.path.startswith('/ext/'):  # управляющие запросы только из нашего окна (пользовательский заголовок не пропустит чужой сайт)
            o = self.headers.get('Origin')
            if self.headers.get('X-MH') != '1' or (o and urlparse(o).hostname not in ('127.0.0.1', 'localhost')): return self.send_error(403)
        try: self.post()
        except json.JSONDecodeError: self.js({'error': 'Некорректный JSON'}, 400)
        except Exception as e: self.js({'error': str(e)}, 500)
    def post(self):
        if self.path == '/ingest': return self.ingest()
        if self.path.startswith('/ext/'): return self.ext_post()
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}'); p = self.path
        if p == '/api/add':
            urls = list(dict.fromkeys(x.strip() for x in d['urls'].splitlines() if x.strip().startswith('http')))
            if d['kind'] == 'site' and d.get('sel'): urls = [d['sel'][0] if not urls else urls[0]]
            for u in urls:
                enqueue({'sel': d.get('sel') or [], 'maxp': int(d.get('maxp') or cfg['maxp']), 'videos': bool(d.get('videos', cfg['videos'])), 'id': next(ids), 'url': u, 'kind': (manga_kind() if d['kind'] == 'mangaurl' else d['kind']), 'res': d.get('res') or cfg['res'], 'afmt': d.get('afmt') or cfg['afmt'], 'depth': int(d.get('depth', cfg['depth'])),
                         'topic': d.get('topic', '').strip(), 'subs': d['subs'] if 'subs' in d else (cfg['subs_langs'] if cfg['subs_on'] else ''), 'thumbs': bool(d.get('thumbs', cfg['thumbs'])), 'first': int(d.get('first') or 0), 'last': int(d.get('last') or 0), 'start_at': float(d.get('start_at') or 0),
                         'daily': bool(d.get('daily')), 'status': 'в очереди', 'pct': 0, 'title': u, 'speed': 0, 'eta': 0, 'cancel': False})
            return self.js({'added': len(urls)})
        if p == '/api/cancel':
            for j in jobs.values():
                if d.get('all') or j['id'] == d.get('id'):
                    j['cancel'] = True
                    if j['status'].startswith(('в очереди', 'запланировано')): j['status'] = 'отменено'
            return self.js({'ok': 1})
        if p == '/api/clear':
            for k in [k for k, j in jobs.items() if j['status'].startswith(('готово', 'отменено', 'ошибка', 'пропущено', 'сохранено', 'частично'))]: del jobs[k]
            return self.js({'ok': 1})
        if p == '/api/preview':
            tok = str(next(ids)); prev[tok] = {'done': 0, 'total': 0, 'size': 0, 'unknown': 0, 'skipped': 0, 'err': [], 'finished': False}
            threading.Thread(target=preview, args=(tok, d), daemon=True).start(); return self.js({'t': tok})
        if p == '/api/progress': return self.js(*legacy_reader_progress.progress_request(d, db, lock))
        if p == '/api/discover':
            tok = str(next(ids)); prev[tok] = {'done': 0, 'total': 0, 'size': 0, 'unknown': 0, 'skipped': 0, 'err': [], 'finished': False, 'pages': []}
            threading.Thread(target=discover, args=(tok, d), daemon=True).start(); return self.js({'t': tok})
        if p == '/api/reveal':  # показать файл или папку материала в проводнике (путь берём только из библиотеки)
            r = sql('select * from items where id=?', (d.get('id'),))
            if not r or r[0]['kind'] == 'link': return self.js({'ok': False})
            t = r[0]['root'] if (r[0]['kind'] in ('manga', 'site') and r[0]['root']) else r[0]['path']
            return self.js({'ok': bool(t and os.path.exists(t) and gamesweep.reveal(t))})
        if p == '/api/game/add': return self.js({'job': new_job(gamelib.thread_key(str(d.get('url') or '').strip()), 'gamecard', title=str(d.get('url'))[:120])}) if str(d.get('url') or '').startswith('http') else self.js({'error': 'нужна ссылка на тему игры'})
        if p == '/api/game/check':
            game_ids = [d['id']] if d.get('id') else None
            return self.js({'job': new_job('games:check', 'gamecheck', ids=game_ids, title='Проверка игр')})
        if p == '/api/game/zip-inspect': return self.js(*inspect_request(d, lambda item_id: next(iter(sql("select * from items where id=? and kind='game'", (item_id,))), None), gamesweep.parse_name, cfg['folder'], cfg.get('games_root', '')))
        if p == '/api/game/incoming': return self.js(*preview_request(d, lambda item_id: next(iter(sql("select * from items where id=? and kind='game'", (item_id,))), None), game_view, gamesweep.parse_name, cfg['folder'], cfg.get('games_root', '')))
        if p == '/api/game/tags': return self.js(*save_tags_request(d, lambda item_id, tags: game_tags.replace_tags(db, lock, item_id, tags)))
        if p == '/api/game/set':
            r = sql("select * from items where id=? and kind='game'", (d.get('id'),))
            if r:
                i = ginfo(r[0])
                if 'auto' in d: i['auto'] = bool(d['auto'])
                if 'note' in d: i['note'] = str(d['note'])[:2000]
                ginfo_save(r[0]['id'], i)
            return self.js({'ok': 1})
        if p == '/api/inbox/confirm': return self.js(inbox_confirm(d))
        if p == '/api/inbox/dismiss':
            if not sql("select 1 from inbox where batch=? and status in ('pending','queued','closing')", (d['batch'],)): sql('delete from inbox where batch=?', (d['batch'],))
            return self.js({'ok': 1})
        if p == '/api/inbox/reopened': sql("update inbox set status='reopened' where id=? and status='closed'", (d['id'],)); return self.js({'ok': 1})
        if p == '/api/ext/approve':
            o = d.get('origin')
            if o in PAIR:
                PAIR.pop(o)
                if d.get('allow'): EXT[o] = secrets.token_urlsafe(24); ext_save()
            return self.js({'ok': 1})
        if p == '/api/ext/forget': EXT.pop(d.get('origin'), None); ext_save(); return self.js({'ok': 1})
        if p == '/api/item/download':
            r = sql('select * from items where id=?', (d['id'],))[0]; src = r['src'] or r['url']; c = classify(src); jk = JOBK.get(c['kind'])
            if jk == 'mangaurl': jk = manga_kind()
            if not jk or c['kind'] == 'unknown': return self.js({'error': 'Для этого источника скачивание пока недоступно'})
            return self.js({'job': new_job(c.get('norm') or src, jk, title=r['title'])})
        if p == '/api/scan': scan(); threading.Thread(target=backfill, daemon=True).start(); return self.js({'ok': 1})
        if p == '/api/edit':
            r = sql('select * from items where id=?', (d['id'],))[0]; path = r['path']; au = d['author'].strip() or r['author']
            if r['kind'] not in ('site', 'manga', 'link', 'game') and path and au != r['author'] and Path(path).exists():
                src = Path(path); dst = src.parent.parent / safe(au); dst.mkdir(parents=True, exist_ok=True)
                for f in list(src.parent.iterdir()):
                    if f.stem == src.stem or f.name.startswith(src.stem + '.'): shutil.move(str(f), str(dst / f.name))
                path = str(dst / src.name)
            sql('update items set author=?, topic=?, path=?, thumb=? where id=?', (au, d['topic'].strip() or r['topic'], path, r['thumb'] if r['kind'] in ('site', 'manga', 'link', 'game') else thumb_of(path), d['id']))
            return self.js({'ok': 1})
        if p == '/api/delete':
            r = sql('select * from items where id=?', (d['id'],)); error = delete_guard.check_request(d, r[0] if r else None)
            if error: return self.js({'error': error[0]}, error[1])
            if d.get('files') and r[0]['kind'] not in ('link', 'game') and r[0]['path']:
                try: delete_files.remove_files(r[0])
                except OSError: return self.js({'error': 'Не удалось удалить все файлы. Часть уже могла быть удалена; запись сохранена.'}, 500)
            try: sql('delete from items where id=?', (d['id'],))
            except sqlite3.Error: return self.js({'error': 'Не удалось удалить запись. Если выбрано удаление с диска, файлы уже могли быть удалены.'}, 500)
            return self.js({'ok': 1})
        if p == '/api/settings':
            if 'games_layout' in d and d['games_layout'] not in game_scan.LAYOUTS: return self.js({'error': 'Неизвестная структура папок игр'}, 400)
            old_gr = cfg.get('games_root'); cfg.update({k: d[k] for k in ('folder', 'skip', 'cookie_file', 'cookie_browser', 'games_root', 'games_layout', 'show_browser', 'browser', 'limit_mb', 'workers', 'res', 'afmt', 'subs_on', 'subs_langs', 'thumbs', 'depth', 'maxp', 'videos', 'manga_via', 'games_check_hours') if k in d}); _op[0] = None; spawn_workers()
            if cfg.get('games_root') and cfg['games_root'] != old_gr: threading.Thread(target=games_scan, args=(cfg['games_root'],), daemon=True).start()
            CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), 'utf-8'); return self.js(cfg)
        self.send_error(404)

def main():
    scan(); threading.Thread(target=backfill, daemon=True).start()
    spawn_workers(); threading.Thread(target=settle_loop, daemon=True).start(); threading.Thread(target=game_auto_loop, daemon=True).start()
    if cfg.get('games_root'): threading.Thread(target=games_scan, args=(cfg['games_root'],), daemon=True).start()
    print('MediaHub: http://127.0.0.1:8765'); os.environ.get('MEDIAHUB_NO_BROWSER') or webbrowser.open('http://127.0.0.1:8765'); ThreadingHTTPServer(('127.0.0.1', 8765), H).serve_forever()
