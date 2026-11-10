"""Select a single HTTP byte range; malformed or unsupported ranges are ignored."""
import re

UNSATISFIABLE = object()
_RANGE = re.compile(r'bytes=([0-9]*)-([0-9]*)', re.IGNORECASE)


def _bounded_number(value, size):
    digits = value.lstrip('0') or '0'
    # Avoid Python's integer-string limit and excessive integer allocations.
    return size + 1 if len(digits) > len(str(size)) else int(digits)


def select_range(header, size):
    """Return None (full), UNSATISFIABLE (416), or inclusive (start, end)."""
    if not header:
        return None
    match = _RANGE.fullmatch(header.strip())
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        suffix = _bounded_number(last, size)
        if size == 0 or suffix == 0:
            return UNSATISFIABLE
        return max(0, size - suffix), size - 1
    start = _bounded_number(first, size)
    end = _bounded_number(last, size) if last else size - 1
    if last and end < start:
        return None  # Invalid range, not a valid but unsatisfiable one.
    if start >= size:
        return UNSATISFIABLE
    return start, min(end, size - 1)
