"""Read-only endpoint used to validate browser-local recent items."""
import re
import sqlite3

from storage import recent_items


def get(handler, path, sql):
    match = re.fullmatch(r'/api/recent/([0-9]{1,19})', path)
    if not match or not 1 <= int(match.group(1)) <= 2**63 - 1:
        return handler.js({'error': 'Материал не найден'}, 404)
    try:
        rows = sql("select id,title,kind,url,root,path,added from items where id=? and kind in ('video','audio','manga')", (int(match.group(1)),))
        item = recent_items.describe(rows[0]) if rows else None
    except sqlite3.Error:
        return handler.js({'error': 'Не удалось проверить материал'}, 500)
    if not item:
        return handler.js({'error': 'Материал отсутствует или недоступен'}, 404)
    return handler.js(item)
