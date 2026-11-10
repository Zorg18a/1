"""Validation and application service for game tags."""


def normalize_tags(value):
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError('Передайте список не более чем из 20 тегов')
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, str) or any(ord(c) < 32 for c in raw) or ',' in raw:
            raise ValueError('Тег должен быть текстом без запятых и управляющих символов')
        tag = ' '.join(raw.split())
        if not tag or len(tag) > 40:
            raise ValueError('Длина тега должна быть от 1 до 40 символов')
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def save_tags_request(data, replace):
    if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] < 1:
        return {'error': 'Некорректный идентификатор игры'}, 400
    try:
        tags = normalize_tags(data.get('tags'))
    except ValueError as exc:
        return {'error': str(exc)}, 400
    if not replace(data['id'], tags):
        return {'error': 'Игра не найдена'}, 404
    return {'tags': tags}, 200
