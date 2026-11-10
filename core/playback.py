"""Playback position rules shared by storage and future HTTP endpoints."""
import math

MIN_POSITION = 5.0
FINISH_MARGIN = 10.0
MAX_SECONDS = 10 * 365 * 24 * 60 * 60


def validate_item_id(item_id):
    if type(item_id) is not int or not 1 <= item_id <= 2**63 - 1:
        raise ValueError('Некорректный идентификатор материала')
    return item_id


def validate_position(pos, dur):
    values = []
    for value in (pos, dur):
        if type(value) not in (int, float):
            raise ValueError('Позиция и длительность должны быть числами')
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError('Позиция или длительность слишком велики') from exc
        if not math.isfinite(number) or not 0 <= number <= MAX_SECONDS:
            raise ValueError('Позиция или длительность вне допустимого диапазона')
        values.append(number)
    return tuple(values)


def is_finished(pos, dur):
    pos, dur = validate_position(pos, dur)
    return dur > 0 and pos >= dur - FINISH_MARGIN
