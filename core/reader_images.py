"""Serve reader pages with optional process-local library identity checks."""
import hmac
from pathlib import Path
import re
from urllib.parse import parse_qs

from storage import reader_snapshot


def get(handler, match, query, sql):
    params = parse_qs(query, keep_blank_values=True)
    values = params.get('identity')
    if values is not None and (len(values) != 1 or not re.fullmatch(r'[0-9a-f]{64}', values[0])):
        return handler.js({'error': 'Некорректная идентичность страницы манги'}, 400)
    rows = sql('select * from items where id=? and kind=?', (match.group(1), 'manga'))
    if not rows:
        return handler.send_error(404)
    item = rows[0]
    if values is not None and not hmac.compare_digest(
            reader_snapshot.view_identity(item['id'], item['url'], item['root']), values[0]):
        return handler.js({'error': 'Запись манги изменилась. Обновите читалку.'}, 409)
    return handler.file(Path(item['root']) / 'chapters' / match.group(2) / match.group(3))
