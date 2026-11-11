"""Local-only HTTP download handler for an in-memory database snapshot."""
import logging
import threading

from storage import backup_download

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
        handler.end_headers()
        try:
            handler.wfile.write(data)
        except OSError:
            logging.warning('Передача копии прервалась; проверьте загрузки браузера')
    finally:
        _busy.release()
