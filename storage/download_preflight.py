"""Read-only, point-in-time observations; no file or directory creation."""
import os
from pathlib import Path
import shutil
import stat


def folder_status(folder):
    if not isinstance(folder, str) or not folder or '\0' in folder or len(folder) > 32768:
        return {'state': 'invalid', 'free_bytes': None}
    if os.name == 'nt' and (folder.startswith('\\\\') or folder.startswith('//')):
        return {'state': 'network_skipped', 'free_bytes': None}
    try:
        path = Path(folder)
        if not path.is_absolute():
            return {'state': 'relative', 'free_bytes': None}
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode):
            return {'state': 'not_directory', 'free_bytes': None}
        try:
            free = str(shutil.disk_usage(path).free)
        except OSError:
            free = None
        return {'state': 'directory', 'free_bytes': free}
    except FileNotFoundError:
        return {'state': 'missing', 'free_bytes': None}
    except (OSError, ValueError):
        return {'state': 'unknown', 'free_bytes': None}


def tool_status(ff_dir):
    # yt-dlp is explicitly configured with this directory whenever it exists.
    try:
        explicit = Path(ff_dir).exists()
        def present(name):
            if explicit:
                target = Path(ff_dir) / (name + ('.exe' if os.name == 'nt' else ''))
                try:
                    return 'found' if stat.S_ISREG(target.stat().st_mode) else 'missing'
                except FileNotFoundError:
                    return 'missing'
            return 'found' if shutil.which(name) else 'missing'
        return {'source': 'app_folder' if explicit else 'path',
                'ffmpeg': present('ffmpeg'), 'ffprobe': present('ffprobe')}
    except (OSError, ValueError, TypeError):
        return {'source': 'unknown', 'ffmpeg': 'unknown', 'ffprobe': 'unknown'}
