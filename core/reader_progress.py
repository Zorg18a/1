"""Validation for the isolated, future timestamped reader-progress writer."""
import re

from core.playback import validate_item_id


def validate_progress(item_id, chapter_id, page):
    validate_item_id(item_id)
    if type(chapter_id) is int:
        chapter_id = str(chapter_id)
    if not isinstance(chapter_id, str) or not re.fullmatch(r'[0-9]{1,30}', chapter_id):
        raise ValueError('Некорректный идентификатор главы')
    if type(page) is not int or not 0 <= page <= 2**63 - 1:
        raise ValueError('Некорректный номер страницы')
    return item_id, chapter_id, page
