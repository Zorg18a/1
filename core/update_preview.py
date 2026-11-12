"""Conservative, read-only suggestions for manually downloaded game archives."""
from storage.incoming_downloads import ARCHIVE_EXTENSIONS, incoming_folder, list_archives
from core.save_preview import save_preview_request
from core import local_game_match

DISPLAY_LIMIT = 50


def archive_stem(name):
    for extension in sorted(ARCHIVE_EXTENSIONS, key=len, reverse=True):
        if name.lower().endswith(extension):
            return name[:-len(extension)]
    return name


def preview_request(data, lookup, game_view, parse_name, download_folder, games_root, db=None, lock=None, cfg=None):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] < 1:
        return {'error': 'Некорректный идентификатор игры'}, 400
    game = lookup(data['id'])
    if game is None:
        return {'error': 'Игра не найдена'}, 404
    if 'mode' in data:
        if data['mode'] == 'local_search':
            return local_game_match.find(game, games_root, parse_name)
        if data['mode'] == 'local_link':
            if db is None or lock is None or cfg is None:
                return {'error': 'Связывание недоступно'}, 503
            return local_game_match.link(data, db, lock, cfg)
        if data['mode'] not in ('saves', 'save_inventory'):
            return {'error': 'Неизвестный режим просмотра'}, 400
        return save_preview_request(data, game, game_view, games_root)
    try:
        folder = incoming_folder(download_folder, games_root)
        archives, scan_truncated = list_archives(folder)
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except PermissionError:
        return {'error': 'Нет доступа к папке входящих загрузок'}, 403
    except (FileExistsError, NotADirectoryError):
        return {'error': 'Путь входящих загрузок занят файлом'}, 400
    except OSError:
        return {'error': 'Не удалось открыть папку входящих загрузок'}, 500
    key = parse_name(game['title'])['key']
    matches = []
    for archive in archives:
        parsed = parse_name(archive_stem(archive['name']))
        if key and parsed['key'] == key:
            matches.append({**archive, 'version': parsed['text']})
    matches.sort(key=lambda item: (-item['mtime'], item['name'].casefold(), item['name']))
    view = game_view(game)
    return {'folder': str(folder), 'title': game['title'], 'installed_path': view['path'],
            'installed_version': view['version'], 'latest_version': view['latest'],
            'candidates': matches[:DISPLAY_LIMIT], 'truncated': scan_truncated or len(matches) > DISPLAY_LIMIT}, 200
