"""Choose an existing game card, preferring an explicit on-disk association."""
import difflib
import json
import os
import re


def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def find_game(sql, name_key, key, title='', path=None):
    if path:
        rows = [r for r in sql("select * from items where kind='game'")
                if r['path'] and _path_key(r['path']) == _path_key(path)]
        manual = []
        for row in rows:
            try:
                info = json.loads(row['info'] or '{}')
                marked = info.get('mediahub_manual_game_path_v1') if isinstance(info, dict) else None
                if isinstance(marked, str) and marked and _path_key(marked) == _path_key(path):
                    manual.append(row)
            except (ValueError, TypeError):
                continue
        if manual and len(rows) > 1:
            raise ValueError('Одна папка связана с несколькими карточками; сканирование остановлено')
        if manual:
            return manual[0]
    rows = sql("select * from items where kind='game' and url=?", ('game:' + key,))
    if rows:
        return rows[0]
    best, score = None, 0.0
    for row in sql("select * from items where kind='game'"):
        k = row['url'][5:] if str(row['url']).startswith('game:') else name_key(row['title'])
        if re.findall(r'\d+', k) != re.findall(r'\d+', key):
            continue
        similarity = difflib.SequenceMatcher(None, k, key).ratio()
        if similarity > score:
            best, score = row, similarity
    return best if score >= 0.9 else None
