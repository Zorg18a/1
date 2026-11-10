"""Serialize confirmations in this process; this does not make them atomic."""
from functools import wraps
from threading import Lock

_confirm_lock = Lock()


def serialize_confirm(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with _confirm_lock:
            return function(*args, **kwargs)
    return locked
