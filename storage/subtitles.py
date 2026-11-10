"""Bounded, neighbour-only subtitle lookup and guarded reading."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat

from core.subtitle_rules import MAX_BYTES, SubtitleError, subtitle_name, to_webvtt
from storage import guarded_read

MAX_ENTRIES = 5000
MAX_TRACKS = 64


@contextmanager
def _folder(media_path):
    if not isinstance(media_path, str) or not media_path:
        raise SubtitleError('Нет пути к материалу')
    media = Path(media_path)
    if not media.is_absolute() or '..' in media.parts or not media.name:
        raise SubtitleError('Нужен абсолютный путь к материалу')
    if os.name == 'nt':
        yield media, None
        return
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY') or os.open not in os.supports_dir_fd:
        raise SubtitleError('Защищённое чтение на этой системе недоступно')
    try:
        fd = os.open(media.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SubtitleError('Папка субтитров недоступна') from exc
    try:
        yield media, fd
    finally:
        os.close(fd)


@contextmanager
def _open_file(media, directory_fd, name):
    try:
        if os.name == 'nt':
            with guarded_read.open_guarded_file(str(media.parent), name) as stream:
                yield stream, stream.stat
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0)
            fd = os.open(name, flags, dir_fd=directory_fd)
            try:
                stream = os.fdopen(fd, 'rb')
            except BaseException:
                os.close(fd)
                raise
            with stream:
                yield stream, lambda: os.fstat(stream.fileno())
    except (OSError, guarded_read.GuardedReadError) as exc:
        raise SubtitleError('Субтитры недоступны или небезопасны') from exc


def _check(info):
    if (not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and info.st_nlink != 1)
            or info.st_size > MAX_BYTES):
        raise SubtitleError('Субтитры недоступны или небезопасны')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _revision(name, info):
    material = (name + '\0' + repr(_identity(info))).encode('utf-8', 'surrogatepass')
    return hashlib.blake2s(material, digest_size=16).hexdigest()


def _tracks(media, directory_fd):
    matches = []
    try:
        with os.scandir(str(media.parent) if os.name == 'nt' else directory_fd) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES:
                    raise SubtitleError('Слишком много файлов в папке субтитров')
                metadata = subtitle_name(media.name, entry.name)
                if metadata:
                    matches.append((entry.name, *metadata))
                    if len(matches) > MAX_TRACKS:
                        raise SubtitleError('Слишком много дорожек субтитров')
    except OSError as exc:
        raise SubtitleError('Папка субтитров недоступна') from exc
    tracks = []
    for name, lang, label, ext in sorted(matches, key=lambda x: (x[1].lower(), x[0].casefold(), x[0])):
        try:
            with _open_file(media, directory_fd, name) as (_, info):
                stat_info = info()
                _check(stat_info)
                revision = _revision(name, stat_info)
        except SubtitleError:
            continue
        tracks.append({'name': name, 'lang': lang, 'label': label, 'extension': ext, 'revision': revision})
    return tracks


def list_tracks(media_path):
    with _folder(media_path) as (media, directory_fd):
        return _tracks(media, directory_fd)


def read_track(media_path, index, revision=None):
    if type(index) is not int or not 0 <= index < MAX_TRACKS:
        raise SubtitleError('Дорожка субтитров не найдена')
    with _folder(media_path) as (media, directory_fd):
        tracks = _tracks(media, directory_fd)
        if index >= len(tracks):
            raise SubtitleError('Дорожка субтитров не найдена')
        track = tracks[index]
        if revision is not None and revision != track['revision']:
            raise SubtitleError('Список субтитров изменился')
        with _open_file(media, directory_fd, track['name']) as (stream, info):
            before = info()
            _check(before)
            if _revision(track['name'], before) != track['revision']:
                raise SubtitleError('Субтитры изменились')
            chunks, remaining = [], MAX_BYTES + 1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = info()
            if _identity(before) != _identity(after) or not remaining:
                raise SubtitleError('Субтитры изменились или слишком большие')
    return to_webvtt(b''.join(chunks), track['extension'])
