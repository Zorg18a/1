"""HTTP delivery for subtitles attached to video/audio library entries."""
import re
from urllib.parse import parse_qs, urlsplit

from core.subtitle_rules import SubtitleError, public_tracks
from storage import subtitles


def get(handler, path, sql):
    metadata = re.fullmatch(r'/api/subtitles/([0-9]{1,19})', path)
    content = re.fullmatch(r'/sub/([0-9]{1,19})/([0-9]{1,2})\.vtt', path)
    if not metadata and not content:
        return handler.js({'error': 'Субтитры не найдены'}, 404)
    match = metadata or content
    item_id = int(match.group(1))
    if not 1 <= item_id <= 2**63 - 1:
        return handler.js({'error': 'Материал не найден'}, 404)
    rows = sql("select kind,path from items where id=? and kind in ('video','audio')", (item_id,))
    if not rows:
        return handler.js({'error': 'Материал не найден'}, 404)
    try:
        if metadata:
            tracks = subtitles.list_tracks(rows[0]['path'])
            return handler.js({'subs': public_tracks(item_id, tracks)})
        query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
        revisions = query.get('rev', [])
        if revisions and (len(revisions) != 1 or not re.fullmatch(r'[0-9a-f]{32}', revisions[0])):
            raise SubtitleError('Некорректная версия субтитров')
        body = subtitles.read_track(rows[0]['path'], int(match.group(2)), revisions[0] if revisions else None)
    except SubtitleError:
        return handler.js({'error': 'Субтитры недоступны'}, 404)
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/vtt; charset=utf-8')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except OSError:
        return
