"""Load reader metadata and compare the library key with the manga manifest."""
import json
from pathlib import Path
import re

from storage import reader_snapshot


def manga_info(item_id, sql):
    rows = sql('select * from items where id=? and kind=?', (item_id, 'manga'))
    if not rows:
        return {'error': 'not found'}
    item = rows[0]
    manifest = json.loads((Path(item['root']) / 'manifest.json').read_text('utf-8'))
    slug = manifest.get('slug')
    valid = isinstance(slug, str) and 0 < len(slug) <= 1024 and '\0' not in slug
    matches = valid and isinstance(item['url'], str) and item['url'] == 'manga:' + slug
    progress = sql('select cid,page from progress where slug=? collate binary', (slug,)) if valid else []
    all_chapters = {c['cid']: {'id': c['cid'], 'label': c['label'], 'files': [], 'expected': 0, 'done': False}
                    for c in manifest.get('listed', [])}
    for key, chapter in manifest['chapters'].items():
        all_chapters[key] = dict(chapter, id=key)
    chapters = sorted(all_chapters.values(), key=lambda c: [float(x) for x in re.findall(r'\d+(?:\.\d+)?', c['label'])] or [0])
    return {'title': manifest['title'], 'chapters': chapters, 'total': len(manifest.get('listed', [])),
            'have': len(manifest['chapters']), 'progress': dict(progress[0]) if progress else None,
            'progress_save_allowed': bool(matches), 'progress_slug': slug if matches else None,
            'progress_snapshot': reader_snapshot.token(item_id, slug, progress[0] if progress else None) if matches else None}
