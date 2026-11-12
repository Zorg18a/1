"""Windows NT handle-relative opening; no filesystem policy is implied."""
import os

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes

    class _UnicodeString(ctypes.Structure):
        _fields_ = [('length', wintypes.USHORT), ('maximum_length', wintypes.USHORT),
                    ('buffer', wintypes.LPWSTR)]

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = [('length', wintypes.ULONG), ('root', wintypes.HANDLE),
                    ('name', ctypes.POINTER(_UnicodeString)), ('attributes', wintypes.ULONG),
                    ('security_descriptor', wintypes.LPVOID), ('security_qos', wintypes.LPVOID)]

    class _StatusUnion(ctypes.Union):
        _fields_ = [('status', ctypes.c_long), ('pointer', wintypes.LPVOID)]

    class _IoStatus(ctypes.Structure):
        _fields_ = [('value', _StatusUnion), ('information', ctypes.c_size_t)]

    _nt = ctypes.WinDLL('ntdll')
    _nt.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG,
        ctypes.POINTER(_ObjectAttributes), ctypes.POINTER(_IoStatus), ctypes.POINTER(ctypes.c_longlong),
        wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG]
    _nt.NtCreateFile.restype = ctypes.c_long
    _nt.NtClose.argtypes = [wintypes.HANDLE]
    _nt.NtClose.restype = ctypes.c_long
    _nt.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _nt.RtlNtStatusToDosError.restype = wintypes.ULONG


def open_relative(parent, name, *, directory, shared_write=False):
    """Open one component; shared_write pins a file name but permits data writes."""
    if shared_write and directory:
        raise ValueError('shared_write is only supported for files')
    if (not isinstance(name, str) or not name or name in ('.', '..') or
            any(c in name for c in ('/', '\\', '\x00'))):
        raise ValueError('Expected one path component')
    if os.name != 'nt':
        raise OSError('Handle-relative opening requires Windows')
    length = len(name.encode('utf-16-le'))
    if length > 65532:
        raise ValueError('Path component is too long')
    buffer = ctypes.create_unicode_buffer(name)
    text = _UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
    attributes = _ObjectAttributes(ctypes.sizeof(_ObjectAttributes), parent, ctypes.pointer(text),
                                   0x40, None, None)  # OBJ_CASE_INSENSITIVE
    status_block, handle = _IoStatus(), wintypes.HANDLE()
    # Attribute-only file access may not participate in Windows share checks.
    access = (0x80 | 0x20 if directory else 0x80000000) | 0x100000
    share = 1 | (2 if directory or shared_write else 0)  # no delete; shared_write permits writers
    options = 0x00200000 | 0x20 | (0x1 if directory else 0x40)  # reparse point, synchronous, type
    status = _nt.NtCreateFile(ctypes.byref(handle), access, ctypes.byref(attributes),
                              ctypes.byref(status_block), None, 0, share, 1, options, None, 0)
    if status != 0:
        if handle.value:
            _nt.NtClose(handle)
        raise ctypes.WinError(_nt.RtlNtStatusToDosError(status))
    return handle.value
