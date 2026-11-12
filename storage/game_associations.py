"""Read-only, bounded lookup of existing game-card paths for candidate display."""
import os
import sqlite3

MAX_ROWS = 50000
MAX_SHOWN = 5


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def associations(db, lock, candidates, current_id):
    """Return path ownership snapshot, or unknown for every path if incomplete."""
    paths = {path_key(candidate['path']) for candidate in candidates}
    owners = {path: [] for path in paths}
    counts = {path: 0 for path in paths}
    unknown = lambda: [{'state': 'unknown', 'cards': [], 'extra': 0} for _ in candidates]
    if not paths:
        return []
    try:
        with lock:
            if db.in_transaction:
                return unknown()
            rows = db.execute("select id,title,path from items where kind='game' and path is not null and path!=''")
            for number, row in enumerate(rows, 1):
                if number > MAX_ROWS:
                    return unknown()
                if not isinstance(row['path'], str):
                    return unknown()
                key = path_key(row['path'])
                if key not in owners:
                    continue
                counts[key] += 1
                if len(owners[key]) < MAX_SHOWN:
                    title = row['title'] if isinstance(row['title'], str) else ''
                    owners[key].append({'id': row['id'], 'title': title[:160]})
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return unknown()
    result = []
    for candidate in candidates:
        key = path_key(candidate['path'])
        cards, count = owners[key], counts[key]
        state = ('multiple' if count > 1 else 'none' if not count else
                 'this' if cards[0]['id'] == current_id else 'other')
        result.append({'state': state, 'cards': cards, 'extra': max(0, count - len(cards))})
    return result
