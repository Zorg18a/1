"""Translate a read-only save-location search into API responses."""
from storage.save_discovery import DiscoveryBusy, discover_saves
from storage.save_inventory import inventory_saves


def save_preview_request(data, game, game_view, games_root):
    if set(data) != {'id', 'mode'}:
        return {'error': 'Поиск сохранений принимает только id игры и режим'}, 400
    try:
        view = game_view(game)
        result = (inventory_saves(games_root, view['path']) if data['mode'] == 'save_inventory'
                  else discover_saves(games_root, view['path']))
    except DiscoveryBusy as exc:
        return {'error': str(exc)}, 409
    except ValueError as exc:
        return {'error': str(exc)}, 400
    except PermissionError:
        return {'error': 'Нет доступа к папке игры'}, 403
    except FileNotFoundError:
        return {'error': 'Папка игры или корень библиотеки недоступны'}, 404
    except OSError:
        return {'error': 'Не удалось просмотреть папку игры'}, 500
    return {('save_inventory' if data['mode'] == 'save_inventory' else 'save_preview'): result}, 200
