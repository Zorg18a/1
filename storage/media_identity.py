"""Best-effort identity for a local playback preference, not a security fingerprint."""
import hashlib
import json
import os
from pathlib import Path
import stat


def position_key(item):
    path = item['path']
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        return None
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return None
        fields = [item['id'], item['kind'], item['url'], item['added'], path,
                  info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        return hashlib.sha256(json.dumps(fields, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()
    except (OSError, ValueError, TypeError):
        return None
