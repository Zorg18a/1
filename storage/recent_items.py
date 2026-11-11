"""Best-effort identity and current metadata for browser-local opening history."""
import hashlib
import json
from pathlib import Path

from storage import media_identity, reader_snapshot


def describe(item):
    kind = item['kind']
    if kind not in ('video', 'audio', 'manga'):
        return None
    title = item['title'] if isinstance(item['title'], str) and item['title'] else 'Без названия'
    if kind == 'manga':
        root, url = item['root'], item['url']
        if not isinstance(root, str) or not root or not isinstance(url, str) or not Path(root).is_absolute():
            return None
        try:
            if not (Path(root) / 'manifest.json').is_file():
                return None
            values = [item['id'], kind, url, root, item['added']]
            if not all(value is None or type(value) in (str, int) for value in values):
                return None
            identity = hashlib.sha256(json.dumps(values, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()
            live = reader_snapshot.view_identity(item['id'], url, root)
        except (OSError, ValueError, TypeError):
            return None
    else:
        identity = live = media_identity.position_key(item)
        if not identity:
            return None
    return {'id': str(item['id']), 'kind': kind, 'title': title[:300], 'identity': identity, 'live_identity': live}
