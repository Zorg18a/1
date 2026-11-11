"""Read-only player preview metadata; playback positions are not enabled yet."""
import re
import sqlite3

from core.subtitle_rules import SubtitleError, public_tracks
from storage import media_identity, subtitles


def get(handler, path, sql):
    match = re.fullmatch(r'/api/player-preview/([0-9]{1,19})', path)
    if not match or not 1 <= int(match.group(1)) <= 2**63 - 1:
        return handler.js({'error': 'Материал не найден'}, 404)
    item_id = int(match.group(1))
    try:
        rows = sql("select id,title,kind,path,thumb,url,added from items where id=? and kind in ('video','audio')", (item_id,))
    except sqlite3.Error:
        return handler.js({'error': 'Не удалось загрузить материал'}, 500)
    if not rows:
        return handler.js({'error': 'Материал не найден'}, 404)
    item = rows[0]
    warning = False
    try:
        tracks = subtitles.list_tracks(item['path'])
    except SubtitleError:
        tracks, warning = [], True
    return handler.js({'id': item_id, 'title': item['title'] or 'Материал', 'kind': item['kind'],
                       'src': f'/f/{item_id}', 'cover': f'/t/{item_id}' if item['thumb'] else '',
                       'subs': public_tracks(item_id, tracks),
                       'subtitle_warning': warning, 'position_available': False,
                       'local_position_identity': media_identity.position_key(item)})
