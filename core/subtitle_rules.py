"""Subtitle naming and bounded SRT/WebVTT conversion."""
import re
from pathlib import PurePath

MAX_BYTES = 5_000_000
_LANG = re.compile(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}\Z')
_TIME = re.compile(r'(?m)^([ \t]*\d{2,}:\d{2}:\d{2}),(\d{3})([ \t]*-->[ \t]*\d{2,}:\d{2}:\d{2}),(\d{3})(?=[ \t\n]|$)')


class SubtitleError(ValueError):
    """Subtitle is invalid, too large, inaccessible, or unsafe."""


def subtitle_name(media_name, filename):
    """Return (language, label, extension) only for a matching neighbour name."""
    if not isinstance(filename, str) or any(c in filename for c in ('/', '\\', '\x00')):
        return None
    if not media_name or any(c in media_name for c in ('/', '\\', '\x00')):
        return None
    stem = PurePath(media_name).stem
    ext = PurePath(filename).suffix.lower()
    if not stem or ext not in ('.srt', '.vtt'):
        return None
    base = filename[:-len(ext)]
    if base == stem:
        return ('und', 'Без языка', ext)
    if not base.startswith(stem + '.'):
        return None
    lang = base[len(stem) + 1:]
    if not _LANG.fullmatch(lang):
        return None
    primary = lang.split('-')[0].lower()
    label = {'ru': 'Русский', 'en': 'English'}.get(primary, lang)
    return (lang, label, ext)


def public_tracks(item_id, tracks):
    return [{'n': index, 'lang': track['lang'], 'label': track['label'],
             'url': f"/sub/{item_id}/{index}.vtt?rev={track['revision']}"}
            for index, track in enumerate(tracks)]


def to_webvtt(data, extension):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise SubtitleError('Субтитры слишком большие')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = data.decode('cp1251')
        except UnicodeDecodeError as exc:
            raise SubtitleError('Неизвестная кодировка субтитров') from exc
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if extension.lower() == '.srt':
        text = 'WEBVTT\n\n' + _TIME.sub(r'\1.\2\3.\4', text)
    elif extension.lower() == '.vtt':
        if not re.match(r'\AWEBVTT(?:[ \t][^\n]*)?\n', text):
            raise SubtitleError('Некорректный заголовок WebVTT')
    else:
        raise SubtitleError('Неподдерживаемый формат субтитров')
    return text.encode('utf-8')
