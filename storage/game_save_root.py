"""Select the root for read-only saves without trusting a client-supplied path."""
import json
import os

from storage.extra_game_root import validate_root


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def save_root(game, configured_root):
    # Old cards do not carry the extra-root marker and retain the old behavior.
    if 'info' not in game.keys() or not game['info']:
        return configured_root
    try:
        info = json.loads(game['info'])
    except (TypeError, ValueError) as exc:
        raise ValueError('Не удалось прочитать данные карточки игры') from exc
    if not isinstance(info, dict):
        raise ValueError('Неизвестный формат карточки игры')
    if 'mediahub_extra_game_root_v1' not in info:
        return configured_root
    root = validate_root(info['mediahub_extra_game_root_v1'])
    marker, path, inst = info.get('mediahub_manual_game_path_v1'), game['path'], info.get('inst')
    if (not isinstance(marker, str) or not os.path.isabs(marker) or not isinstance(path, str) or
            not os.path.isabs(path) or not isinstance(inst, dict) or not isinstance(inst.get('path'), str) or
            not os.path.isabs(inst['path']) or _key(marker) != _key(path) or _key(marker) != _key(inst['path'])):
        raise ValueError('Дополнительный путь карточки изменился; проверьте связь вручную')
    return root
