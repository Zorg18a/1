"""Read-only ZIP inspection request; installation is deliberately unavailable."""
import re

from core.update_preview import archive_stem
from core.zip_rules import ArchiveRejected
from storage.incoming_downloads import incoming_folder, list_archives
from storage.zip_inspection import ArchiveChanged, inspect_zip
from storage.zip_content import VerificationBusy


def inspect_request(data, lookup, parse_name, download_folder, games_root):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] < 1:
        return {'error': 'Некорректный идентификатор игры'}, 400
    verify_data = data.get('verify_data', False)
    if type(verify_data) is not bool:
        return {'error': 'Некорректный режим проверки ZIP'}, 400
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
        result = inspect_zip(folder / name, identity, verify_data=verify_data)
    except VerificationBusy as exc:
        return {'error': str(exc)}, 409
    except ArchiveChanged as exc:
        return {'error': str(exc)}, 409
    except ArchiveRejected as exc:
        return {'error': str(exc)}, 422
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except PermissionError:
        return {'error': 'Нет доступа к архиву'}, 403
    except OSError:
        return {'error': 'Не удалось прочитать архив'}, 500
    return {'inspection': result}, 200
