"""Read local artwork and store bounded copies without changing game files."""
import hashlib
import os
from pathlib import Path
import tempfile

MAX_COVER_BYTES = 8_000_000
_NAMES = ('cover', 'folder', 'poster')
_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')


def image_extension(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[4:12] in (b'ftypavif', b'ftypavis'):
        return 'avif'
    return None


def cache_bytes(data, download_folder):
    """Return a unique completed cache file; never overwrite an existing file."""
    extension = image_extension(data)
    if not extension or len(data) > MAX_COVER_BYTES:
        raise ValueError('Неподдерживаемый формат или слишком большая обложка')
    if not isinstance(download_folder, (str, os.PathLike)) or not str(download_folder).strip():
        raise ValueError('Не указана папка загрузок')
    folder = Path(download_folder) / 'covers'
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:16]
    fd, name = tempfile.mkstemp(prefix=f'game-{digest}-', suffix='.' + extension, dir=folder)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        return str(Path(name).absolute())
    except Exception:
        try:
            os.unlink(name)  # Only the incomplete file created by this call.
        except OSError:
            pass
        raise


def local_cover_candidates(game_path):
    """Only explicit artwork names in the chosen game directory, never follow links."""
    folder = Path(game_path)
    if folder.is_symlink() or not folder.is_dir():
        return []
    with os.scandir(folder) as entries:
        files = {entry.name.casefold(): entry.path for entry in entries
                 if entry.is_file(follow_symlinks=False)}
    return [Path(files[stem + suffix]) for stem in _NAMES for suffix in _EXTENSIONS
            if stem + suffix in files]


def cache_local_cover(game_path, download_folder):
    for path in local_cover_candidates(game_path):
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(path, flags), 'rb') as source:
            data = source.read(MAX_COVER_BYTES + 1)
        if image_extension(data) and len(data) <= MAX_COVER_BYTES:
            return cache_bytes(data, download_folder)
    return ''
