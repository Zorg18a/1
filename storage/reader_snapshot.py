"""Process-local fingerprints of the actual SQLite progress values; no schema changes.

This detects changed values, not changes that return to the same values (ABA).
A process restart invalidates all tokens. Tokens are not persistent revisions.
"""
import hashlib
import hmac
import secrets
import struct

_KEY = secrets.token_bytes(32)


def _value(value):
    if value is None:
        return b'n'
    if type(value) is int:
        return b'i' + str(value).encode('ascii')
    if type(value) is float:
        return b'f' + struct.pack('>d', value)
    if isinstance(value, str):
        return b't' + value.encode('utf-8')
    if isinstance(value, bytes):
        return b'b' + value
    raise TypeError('Unsupported SQLite value')


def token(item_id, slug, row):
    """Fingerprint item key and absence or exact types and values of cid/page."""
    values = [item_id, slug, row is not None]
    if row is not None:
        values.extend((row[0], row[1]))
    digest = hmac.new(_KEY, digestmod=hashlib.sha256)
    for value in values:
        part = b'1' if value is True else b'0' if value is False else _value(value)
        digest.update(struct.pack('>Q', len(part)))
        digest.update(part)
    return digest.hexdigest()


def identity(item_id, slug, root):
    """Opaque process-local identity of an item and the exact stored root value."""
    digest = hmac.new(_KEY, b'mediahub-reader-root-v1\0', hashlib.sha256)
    for value in (item_id, slug, root):
        part = _value(value)
        digest.update(struct.pack('>Q', len(part)))
        digest.update(part)
    return digest.hexdigest()
