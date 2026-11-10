"""Compare possible save locations with ZIP names, without planning an installation."""
from pathlib import Path
import unicodedata


def _canonical(parts):
    return tuple(unicodedata.normalize('NFC', unicodedata.normalize('NFC', p).casefold()) for p in parts)


def compare_paths(preview, entries):
    nodes = {}
    for entry in entries:
        parts = _canonical(entry['path'].rstrip('/').split('/'))
        for end in range(1, len(parts) + 1):
            kind = 'directory' if end < len(parts) or entry['kind'] == 'directory' else 'file'
            nodes[parts[:end]] = kind
    results = []
    for candidate in preview['candidates']:
        parts = Path(candidate['path']).parts
        if not parts or any('\\' in part or '/' in part for part in parts):
            relation = 'unsupported_name'
        else:
            key = _canonical(parts)
            if any(nodes.get(key[:end]) == 'file' for end in range(1, len(key))):
                relation = 'ancestor_file'
            elif key not in nodes:
                relation = 'not_found'
            elif candidate['kind'] != nodes[key]:
                relation = 'type_conflict'
            elif candidate['kind'] == 'file':
                relation = 'file_same_path'
            else:
                relation = 'directory_shared'
        results.append({**candidate, 'relation': relation})
    return {'game_folder': preview['game_folder'], 'incomplete': preview['incomplete'],
            'scanned': preview['scanned'], 'skipped': preview['skipped'], 'candidates': results}
