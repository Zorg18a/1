"""Display search only: allow joined or separated words without changing game identity."""


def compact(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


def contains(value, query):
    if not isinstance(value, str) or not isinstance(query, str):
        return False
    text, needle = value.casefold(), query.casefold()
    if needle in text:
        return True
    key = compact(needle)
    return bool(key) and key in compact(text)
