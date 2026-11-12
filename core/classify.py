"""Classify incoming URLs without network or application state."""
import re
from urllib.parse import parse_qs, urlparse

from core import gamelib, pornolab


def classify(url):  # тип материала и ключ для поиска в библиотеке (по адресу, без запросов в сеть)
    u = urlparse(url); h = (u.hostname or '').lower(); h = h[4:] if h.startswith('www.') else h; q = parse_qs(u.query); p = u.path; r = {'kind': 'unknown', 'host': h, 'key': url}
    m = re.match(r'^/manga/([a-z0-9-]+)', p)
    if h == 'senkuro.me' and m: return dict(r, kind='manga', key='manga:' + m.group(1), norm=f'https://senkuro.me/manga/{m.group(1)}')
    if h in ('youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be'):
        vid = p.strip('/') if h == 'youtu.be' else (q.get('v') or [''])[0]; lst = (q.get('list') or [''])[0]
        if p == '/playlist' and lst: return dict(r, kind='playlist', key='https://www.youtube.com/playlist?list=' + lst)
        if p.startswith(('/@', '/channel/', '/c/', '/user/')): return dict(r, kind='playlist', key=url.split('?')[0].split('#')[0])
        if vid: return dict(r, kind='audio' if h == 'music.youtube.com' else 'video', key='https://www.youtube.com/watch?v=' + vid)
    if h in ('vimeo.com', 'rutube.ru', 'dailymotion.com', 'twitch.tv', 'bilibili.com', 'ok.ru', 'vkvideo.ru', 'tiktok.com'): return dict(r, kind='video')
    if h in ('soundcloud.com', 'bandcamp.com') or h.endswith('.bandcamp.com'): return dict(r, kind='audio')
    if h == 'podcasts.apple.com' or (h == 'open.spotify.com' and p.startswith('/show')) or p.endswith(('.rss', '.xml')): return dict(r, kind='podcast')
    if h == 'f95zone.to' and p.startswith('/threads/'): return dict(r, kind='game', key=gamelib.thread_key(url))
    if pornolab.topic_url(url): return dict(r, key=pornolab.topic_url(url))  # Forum topics are not necessarily games.
    if h in ('store.steampowered.com', 'steamcommunity.com', 'gog.com', 'itch.io', 'store.epicgames.com') or h.endswith('.itch.io'): return dict(r, kind='game')
    return r
