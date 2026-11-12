"""Validated, conflict-aware writes of existing game-card settings."""
import json
import sqlite3

from storage.game_card_write import CardConflict


def save(data, lookup, update):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] < 1:
        return {'error': 'Некорректный идентификатор игры'}, 400
    try:
        row = lookup(data['id'])
        if not row:
            return {'error': 'Карточка игры не найдена'}, 404
        try:
            info = json.loads(row['info'] or '{}')
        except (ValueError, TypeError) as exc:
            raise CardConflict('Данные карточки не читаются; запись отменена.') from exc
        if not isinstance(info, dict):
            raise CardConflict('Неизвестный формат карточки; запись отменена.')
        if 'auto' in data:
            info['auto'] = bool(data['auto'])
        if 'note' in data:
            info['note'] = str(data['note'])[:2000]
        update(row, json.dumps(info, ensure_ascii=False))
        return {'ok': 1}, 200
    except CardConflict as exc:
        return {'error': str(exc)}, 409
    except sqlite3.Error:
        return {'error': 'Не удалось сохранить карточку; проверьте базу и повторите.'}, 500
