"""Validate and save progress without enabling the future timestamped migration."""
import logging
import re
import sqlite3
from storage import legacy_reader_progress


def _integer(value, minimum):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        number = int(value)
    else:
        raise ValueError('Некорректный номер материала или страницы')
    if not minimum <= number <= 2**63 - 1:
        raise ValueError('Некорректный номер материала или страницы')
    return number


def progress_request(data, db, lock):
    if not isinstance(data, dict):
        return {'error': 'Некорректные данные позиции'}, 400
    try:
        item_id = _integer(data.get('id'), 1)
        page = _integer(data.get('page'), 0)
        cid = data.get('cid')
        if type(cid) is int:
            cid = str(cid)
        if not isinstance(cid, str) or not cid or len(cid) > 1024:
            raise ValueError('Некорректный идентификатор главы')
        expected = data.get('slug') if 'slug' in data else None
        if 'slug' in data and (not isinstance(expected, str) or not expected or len(expected) > 1024 or '\0' in expected):
            raise ValueError('Некорректный идентификатор манги')
    except ValueError as exc:
        return {'error': str(exc)}, 400
    try:
        saved = legacy_reader_progress.save(db, lock, item_id, cid, page, expected)
    except legacy_reader_progress.IdentityConflict:
        return {'error': 'Запись манги изменилась или ключ позиции конфликтует. Обновите читалку и проверьте данные.'}, 409
    except (sqlite3.Error, RuntimeError):
        logging.exception('Не удалось сохранить прогресс читалки')
        return {'error': 'Не удалось сохранить позицию. Проверьте базу и подключение.'}, 500
    if not saved:
        return {'error': 'Манга не найдена в библиотеке'}, 404
    return {'ok': 1}, 200
