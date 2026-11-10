"""Reject stale or unconfirmed requests before legacy filesystem deletion."""


def check_request(data, row):
    if row is None:
        return 'Материал не найден; обновите библиотеку', 404
    expected = data.get('expected')
    if not data.get('files') and expected is None:
        return None  # Preserve legacy library-only callers.
    if not isinstance(expected, dict):
        return ('Для удаления файлов нужно повторно подтвердить их расположение' if data.get('files')
                else 'Некорректное подтверждение удаления'), 400
    for key in ('title', 'kind', 'path', 'root'):
        if expected.get(key) != (row[key] or ''):
            return 'Данные материала изменились; обновите библиотеку и проверьте расположение', 409
    return None
