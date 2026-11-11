"""Protected, non-mutating preflight of the saved download settings."""
import threading

from storage import download_preflight

_busy = threading.Lock()


def handle(handler, folder, ff_dir, extension_online):
    lengths = handler.headers.get_all('Content-Length', [])
    if handler.headers.get('Transfer-Encoding') or len(lengths) > 1 or (lengths and lengths[0] != '0'):
        handler.close_connection = True
        return handler.js({'error': 'Проверка не принимает данные'}, 400)
    if not _busy.acquire(blocking=False):
        return handler.js({'error': 'Проверка уже выполняется. Попробуйте позже.'}, 409)
    try:
        result = download_preflight.folder_status(folder)
        return handler.js({'folder': folder if isinstance(folder, str) and len(folder) <= 32768 else None,
                           'directory': result, 'tools': download_preflight.tool_status(ff_dir),
                           'extension_online': bool(extension_online)})
    finally:
        _busy.release()
