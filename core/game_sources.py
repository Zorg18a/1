"""Validate and canonicalize sources supported by the extension game importer."""
import re
from urllib.parse import urlsplit

from core import pornolab


def game_thread_url(value):
    """Accept supported HTTPS topic URLs; never pass arbitrary hosts to the bridge."""
    if pornolab.topic_url(value):
        return pornolab.topic_url(value)
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.hostname != 'f95zone.to' or url.username is not None
                or url.password is not None or url.port not in (None, 443)):
            return None
    except ValueError:
        return None
    if re.search(r'%2f|%5c', url.path, re.I):
        return None
    match = re.match(r'^(/threads/[^/]*\d+)(?:/|$)', url.path)
    return 'https://f95zone.to' + match.group(1) + '/' if match else None


def quick_game_request(data, enqueue):
    """Validate an extension request and enqueue a game-card job."""
    url = game_thread_url(data.get('url')) if isinstance(data, dict) else None
    if not url:
        return {'error': 'Нужна ссылка HTTPS на тему игры f95zone.to или pornolab.net'}, 400
    job_id = enqueue(url, 'gamecard', title=url)
    return {'job': job_id, 'status': 'queued'}, 200
