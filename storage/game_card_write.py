"""Guard existing game-card updates against stale reads and manual path replacement."""
import json
import os


class CardConflict(ValueError):
    """Card or manual path changed; caller must refresh rather than overwrite."""


_FIELDS = ('kind', 'url', 'title', 'author', 'root', 'path', 'info', 'thumb', 'size', 'src')
_MARKER = 'mediahub_manual_game_path_v1'


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _guard_info(row, scan_path):
    try:
        info = json.loads(row['info'] or '{}')
    except (TypeError, ValueError) as exc:
        raise CardConflict('Данные карточки не читаются; запись отменена.') from exc
    if not isinstance(info, dict):
        raise CardConflict('Неизвестный формат карточки; запись отменена.')
    if scan_path is not None and _MARKER in info:
        marker, current = info[_MARKER], row['path']
        if (not isinstance(marker, str) or not marker or not isinstance(current, str) or not current or
                _key(marker) != _key(current) or _key(marker) != _key(scan_path)):
            raise CardConflict('Найденная папка отличается от вручную выбранной связи; проверьте карточку и пути.')


def _unclaimed(db, scan_path, current_id=None):
    owners = db.execute("select id,path from items where kind='game' and path is not null and path!=''")
    for number, owner in enumerate(owners, 1):
        if number > 50000 or not isinstance(owner['path'], str):
            raise CardConflict('Невозможно полностью проверить связи папки; запись отменена.')
        if owner['id'] != current_id and _key(owner['path']) == _key(scan_path):
            raise CardConflict('Папка уже связана с другой карточкой; проверьте связи вручную.')


def _update(db, lock, old, statement, args, scan_path=None):
    with lock:
        if db.in_transaction:
            raise CardConflict('База занята; обновление карточки отменено.')
        try:
            db.execute('begin immediate')
            current = db.execute('select * from items where id=?', (old['id'],)).fetchone()
            if current is None or any(current[k] != old[k] for k in _FIELDS):
                raise CardConflict('Карточка изменилась; обновите её и повторите действие.')
            _guard_info(current, scan_path)
            if scan_path is not None:
                _unclaimed(db, scan_path, old['id'])
            db.execute(statement, (*args, old['id']))
            db.commit()
        except Exception:
            db.rollback()
            raise


def scan(db, lock, row, path, size, info, cover):
    _update(db, lock, row,
            "update items set path=?, size=?, info=?, thumb=case when coalesce(thumb,'')=? and ?!='' then ? else thumb end where id=?",
            (path, size, info, row['thumb'] or '', cover, cover), scan_path=path)


def insert_scan(db, lock, title, author, path, key, size, cover, root, info):
    with lock:
        if db.in_transaction:
            raise CardConflict('База занята; создание карточки отменено.')
        try:
            db.execute('begin immediate')
            _unclaimed(db, path)
            db.execute("insert into items(title,author,topic,kind,path,root,url,size,thumb,src,info) values(?,?,?,?,?,?,?,?,?,?,?)",
                       (title, author, 'Игры', 'game', path, '', 'game:' + key, size, cover, root, info))
            db.commit()
        except Exception:
            db.rollback()
            raise


def metadata(db, lock, row, title, author, thread, info, cover):
    _update(db, lock, row,
            "update items set title=?, author=?, src=?, info=?, thumb=case when coalesce(thumb,'')=? and ?!='' then ? else thumb end where id=?",
            (title, author, thread, info, row['thumb'] or '', cover, cover))


def settings(db, lock, row, info):
    _update(db, lock, row, 'update items set info=? where id=?', (info,))
