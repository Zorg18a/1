"""Local-only HTTP download handler for an in-memory database snapshot."""
import hashlib
import logging
import re
import threading
import time

from storage import backup_download, backup_restore

_busy = threading.Lock()


def download(handler, db, lock):
    if not _busy.acquire(blocking=False):
        return handler.js({'error': 'Копирование уже выполняется. Попробуйте позже.'}, 409)
    try:
        try:
            data = backup_download.snapshot(db, lock)
        except backup_download.BackupError as exc:
            logging.warning('Не удалось подготовить копию базы: %s', exc)
            return handler.js({'error': str(exc)}, 503)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/vnd.sqlite3')
        handler.send_header('Content-Disposition', 'attachment; filename="mediahub-library.db"')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Length', str(len(data)))
        handler.send_header('X-Backup-SHA256', hashlib.sha256(data).hexdigest())
        handler.end_headers()
        try:
            handler.wfile.write(data)
        except OSError:
            logging.warning('Передача копии прервалась; проверьте загрузки браузера')
    finally:
        _busy.release()


def inspect(handler):
    lengths = handler.headers.get_all('Content-Length', [])
    if (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,8}', lengths[0]) or
            handler.headers.get('Transfer-Encoding')):
        handler.close_connection = True
        return handler.js({'error': 'Некорректная длина файла'}, 400)
    length = int(lengths[0])
    if length < 100 or length > backup_download.MAX_BYTES:
        handler.close_connection = True
        return handler.js({'error': 'Размер файла должен быть от 100 байт до 64 МиБ'}, 413)
    if (handler.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/octet-stream':
        handler.close_connection = True
        return handler.js({'error': 'Нужен файл SQLite'}, 415)
    if not _busy.acquire(blocking=False):
        handler.close_connection = True
        return handler.js({'error': 'Другая операция с копией ещё выполняется'}, 409)
    try:
        data = bytearray()
        deadline = time.monotonic() + 30
        previous = handler.connection.gettimeout()
        try:
            while len(data) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                handler.connection.settimeout(remaining)
                block = handler.rfile.read(min(65536, length - len(data)))
                if not block:
                    raise EOFError()
                data.extend(block)
        except (OSError, EOFError):
            handler.close_connection = True
            return handler.js({'error': 'Не удалось полностью получить файл копии'}, 400)
        finally:
            handler.connection.settimeout(previous)
        try:
            counts = backup_restore.inspect_bytes(bytes(data))
        except backup_restore.RestoreError as exc:
            return handler.js({'error': str(exc)}, 400)
        return handler.js({'ok': 1, **counts, 'sha256': hashlib.sha256(data).hexdigest()})
    finally:
        _busy.release()


def handle(handler, db, lock):
    return inspect(handler) if handler.path == '/api/backup/inspect' else download(handler, db, lock)
