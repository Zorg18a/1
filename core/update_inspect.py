"""Read-only ZIP inspection request; installation is deliberately unavailable."""
import re

from core.update_preview import archive_stem
from core.save_compare import compare_paths
from core.zip_rules import ArchiveRejected
from storage.incoming_downloads import incoming_folder, list_archives
from storage.zip_inspection import ArchiveChanged, ensure_identity, inspect_zip
from storage.save_discovery import DiscoveryBusy, discover_saves
from storage.game_save_root import save_root
from storage.zip_content import VerificationBusy

DISPLAY_PATH_LIMIT = 200


def inspect_request(data, lookup, parse_name, download_folder, games_root):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] < 1:
        return {'error': 'Некорректный идентификатор игры'}, 400
    verify_data = data.get('verify_data', False)
    compare_saves = data.get('compare_saves', False)
    list_names = data.get('list_names', False)
    if (type(verify_data) is not bool or type(compare_saves) is not bool or type(list_names) is not bool or
            sum((verify_data, compare_saves, list_names)) > 1):
        return {'error': 'Некорректный режим проверки ZIP'}, 400
    if list_names and set(data) != {'id', 'name', 'identity', 'list_names'}:
        return {'error': 'Список принимает только выбранный архив и id игры'}, 400
    if compare_saves and set(data) - {'id', 'name', 'identity', 'compare_saves'}:
        return {'error': 'Сопоставление принимает только выбранный архив и id игры'}, 400
    name, identity = data.get('name'), data.get('identity')
    if (not isinstance(name, str) or not name.lower().endswith('.zip') or len(name) > 255 or
            any(c in name for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 for c in name) or
            not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity)):
        return {'error': 'Выберите ZIP из списка найденных архивов'}, 400
    game = lookup(data['id'])
    if game is None:
        return {'error': 'Игра не найдена'}, 404
    try:
        folder = incoming_folder(download_folder, games_root, create=False)
        archives, truncated = list_archives(folder)
        entry = next((candidate for candidate in archives if candidate['name'] == name), None)
        if entry is None:
            return {'error': 'Архив не найден в текущем списке; обновите поиск' + (' (список ограничен)' if truncated else '')}, 404
        key = parse_name(game['title'])['key']
        if not key or parse_name(archive_stem(name))['key'] != key:
            return {'error': 'Имя архива не соответствует выбранной игре'}, 400
        if entry['identity'] != identity:
            return {'error': 'Архив изменился: обновите поиск'}, 409
        result = inspect_zip(folder / name, identity, verify_data=verify_data, include_names=compare_saves or list_names)
        if list_names:
            entries = result.pop('_entries')
            result['paths'] = entries[:DISPLAY_PATH_LIMIT]
            result['paths_truncated'] = len(entries) > DISPLAY_PATH_LIMIT
        if compare_saves:
            entries = result.pop('_entries')
            preview = discover_saves(save_root(game, games_root), game['path'])
            ensure_identity(folder / name, identity)
            result['save_comparison'] = compare_paths(preview, entries)
    except (VerificationBusy, DiscoveryBusy) as exc:
        return {'error': str(exc)}, 409
    except ArchiveChanged as exc:
        return {'error': str(exc)}, 409
    except ArchiveRejected as exc:
        return {'error': str(exc)}, 422
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except PermissionError:
        return {'error': 'Нет доступа к архиву или папке игры'}, 403
    except FileNotFoundError:
        return {'error': 'Папка игры или корень библиотеки недоступны'}, 404
    except OSError:
        return {'error': 'Не удалось прочитать архив или папку игры'}, 500
    return {'inspection': result}, 200
