"""Validate a user-entered, one-shot local root for read-only game search."""
import os


def validate_root(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c in value for c in '\0\r\n'):
        raise ValueError('Укажите абсолютный путь к дополнительной папке')
    if value != value.strip() or not os.path.isabs(value):
        raise ValueError('Укажите абсолютный путь к дополнительной папке без лишних пробелов')
    if os.name == 'nt':
        drive, tail = os.path.splitdrive(value)
        if len(drive) != 2 or not drive[0].isascii() or not drive[0].isalpha() or drive[1] != ':' or not tail.startswith(('\\', '/')):
            raise ValueError('Укажите путь с буквой диска, например D:\\Игры; UNC и служебные пути не поддерживаются')
    return value
