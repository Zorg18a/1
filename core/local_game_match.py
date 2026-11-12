"""Explicit candidate search and guarded card-to-folder association."""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time

from storage.game_associations import associations, path_key
from storage.incoming_downloads import stat_identity
from storage.local_game_search import search
from storage.save_discovery import _game_folder

_TOKENS = {}
_LOCK = threading.Lock()
_TTL = 300
_MAX_TOKENS = 1000


def _snapshot(row):
    fields = [row[key] for key in ('title', 'url', 'path', 'info')]
    if any(value is not None and not isinstance(value, str) for value in fields):
        raise ValueError('Неизвестный формат карточки; поиск отменён.')
    digest = hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode('ascii')).digest()
    return row['id'], digest


def _key(path):
    return path_key(path)


def _remember(candidate, root, snapshot):
    now = time.monotonic()
    with _LOCK:
        for key in list(_TOKENS):
            if _TOKENS[key][0] <= now:
                del _TOKENS[key]
        if len(_TOKENS) >= _MAX_TOKENS:
            return None
        token = secrets.token_urlsafe(24)
        _TOKENS[token] = (now + _TTL, candidate, root, snapshot)
        return token


def find(game, root, parse_name, db=None, lock=None, *, allow_link=True):
    try:
        result = search(root, game['title'], parse_name)
        snapshot = _snapshot(game)
        candidates = result['candidates']
        ownership = associations(db, lock, candidates, game['id']) if db is not None and lock is not None else [
            {'state': 'unknown', 'cards': [], 'extra': 0} for _ in candidates]
        for candidate, association in zip(candidates, ownership):
            if allow_link and candidate['kind'] == 'folder' and not game['path'] and association['state'] == 'none':
                candidate['token'] = _remember(dict(candidate), result['root'], snapshot)
            candidate.pop('identity', None)
            candidate['association'] = association
        return result, 200
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except PermissionError:
        return {'error': 'Нет доступа к папке игр'}, 403
    except OSError:
        return {'error': 'Не удалось открыть папку игр'}, 400


def link(data, db, lock, cfg):
    token = data.get('token')
    if not isinstance(token, str) or len(token) > 100:
        return {'error': 'Сначала найдите и выберите папку'}, 400
    with _LOCK:
        saved = _TOKENS.pop(token, None)
    if not saved or saved[0] <= time.monotonic() or saved[3][0] != data['id']:
        return {'error': 'Результат поиска устарел. Выполните поиск заново.'}, 409
    _, candidate, root, snapshot = saved
    try:
        if not cfg.get('games_root') or _key(root) != _key(cfg['games_root']):
            raise ValueError('Корень игр изменился. Выполните поиск заново.')
        folder = _game_folder(root, candidate['path'])
        if stat_identity(os.stat(folder, follow_symlinks=False)) != candidate['identity']:
            raise ValueError('Папка изменилась. Выполните поиск заново.')
        with lock:
            if db.in_transaction:
                return {'error': 'База занята. Повторите поиск позже.'}, 409
            try:
                db.execute('begin immediate')
                row = db.execute("select * from items where id=? and kind='game'", (data['id'],)).fetchone()
                if row is None or _snapshot(row) != snapshot or row['path']:
                    raise ValueError('Карточка изменилась или уже связана с путём. Выполните поиск заново.')
                if not cfg.get('games_root') or _key(root) != _key(cfg['games_root']):
                    raise ValueError('Корень игр изменился. Выполните поиск заново.')
                if stat_identity(os.stat(_game_folder(root, str(folder)), follow_symlinks=False)) != candidate['identity']:
                    raise ValueError('Папка изменилась. Выполните поиск заново.')
                for other in db.execute("select id,path from items where kind='game' and id!=?", (data['id'],)):
                    if other['path'] and _key(other['path']) == _key(str(folder)):
                        raise ValueError('Эта папка уже связана с другой карточкой. Автоматическое объединение отменено.')
                try:
                    info = json.loads(row['info'] or '{}')
                except (TypeError, ValueError):
                    raise ValueError('Не удалось прочитать данные карточки; изменения отменены.')
                if not isinstance(info, dict) or not isinstance(info.get('inst', {}), dict):
                    raise ValueError('Неизвестный формат карточки; изменения отменены.')
                old = info.get('inst', {})
                if old.get('path') and _key(old['path']) != _key(str(folder)):
                    raise ValueError('В карточке указан другой прежний путь; изменения отменены.')
                marker = info.get('mediahub_manual_game_path_v1')
                if marker and (not isinstance(marker, str) or _key(marker) != _key(str(folder))):
                    raise ValueError('В карточке указан другой вручную выбранный путь; изменения отменены.')
                info['inst'] = dict(old, path=str(folder), root=root, version='', versions=1, old=0)
                info['mediahub_manual_game_path_v1'] = str(folder)
                info['update'] = False
                db.execute('update items set path=?,info=? where id=?',
                           (str(folder), json.dumps(info, ensure_ascii=False), data['id']))
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {'ok': 1, 'path': str(folder)}, 200
    except (ValueError, OSError) as exc:
        return {'error': str(exc) if isinstance(exc, ValueError) else 'Папка недоступна; изменения отменены.'}, 409
    except sqlite3.Error:
        return {'error': 'Не удалось сохранить связь. Проверьте базу и повторите поиск.'}, 500
