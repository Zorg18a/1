"""Create a bounded in-memory SQLite snapshot; never write a server-side file."""
from contextlib import closing
import sqlite3
import time

MAX_BYTES = 64 * 1024 * 1024
TIMEOUT = 30.0


class BackupError(Exception):
    pass


def snapshot(db, lock):
    """Return a verified standalone SQLite image, or raise without changing the source.

    Requires serialize/deserialize in the Python SQLite build. SQLite backup handles
    WAL and concurrent writers; only the copy loop has a time limit. The source lock
    is shared with application DB operations, so those wait while the copy is checked.
    """
    with lock:
        if db.in_transaction:
            raise BackupError('База занята транзакцией; попробуйте позже')
        deadline = time.monotonic() + TIMEOUT
        try:
            size = db.execute('pragma page_size').fetchone()[0]
            pages = db.execute('pragma page_count').fetchone()[0]
            if not size or size * pages > MAX_BYTES:
                raise BackupError('База слишком велика для скачивания: предел 64 МиБ')
            def progress(_status, _remaining, total):
                if total * size > MAX_BYTES:
                    raise BackupError('База стала слишком большой для скачивания')
                if time.monotonic() > deadline:
                    raise BackupError('Превышено время копирования базы')
            with closing(sqlite3.connect(':memory:')) as target:
                db.backup(target, pages=128, progress=progress, sleep=0.05)
                if target.execute('pragma integrity_check').fetchall() != [('ok',)]:
                    raise BackupError('Копия не прошла проверку целостности')
                raw = target.serialize()
            if len(raw) > MAX_BYTES or len(raw) < 100 or raw[:16] != b'SQLite format 3\x00':
                raise BackupError('Некорректный размер или формат копии')
            # A backup into memory may retain WAL flags in the on-disk header even
            # though it includes all committed pages and no WAL sidecar. SQLite
            # file-format bytes 18/19 select WAL (2) vs rollback journal (1).
            if raw[18:20] == b'\x02\x02':
                raw = raw[:18] + b'\x01\x01' + raw[20:]
            elif raw[18:20] != b'\x01\x01':
                raise BackupError('Неизвестный формат журнала копии')
            with closing(sqlite3.connect(':memory:')) as verified:
                verified.deserialize(raw)
                if verified.execute('pragma integrity_check').fetchall() != [('ok',)]:
                    raise BackupError('Итоговая копия не прошла проверку целостности')
            return raw
        except BackupError:
            raise
        except (sqlite3.Error, AttributeError, MemoryError, OverflowError) as exc:
            raise BackupError('Не удалось скопировать или проверить базу') from exc
