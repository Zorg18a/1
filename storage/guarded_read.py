"""Windows-only guarded file reader; not exposed to application requests."""
import os
from pathlib import Path, PureWindowsPath
import re


class GuardedReadError(ValueError):
    """The path or filesystem cannot be guarded under this policy."""


class GuardedReadUnsupported(GuardedReadError):
    """Guarded reading is unavailable on this platform or filesystem."""


if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class _FileInfo(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                    ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                    ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.GetFileType.argtypes = [wintypes.HANDLE]
    _kernel.GetFileType.restype = wintypes.DWORD
    _kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetDriveTypeW.restype = wintypes.UINT
    _kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR, wintypes.DWORD]
    _kernel.GetVolumeInformationW.restype = wintypes.BOOL

    _INVALID = ctypes.c_void_p(-1).value
    _OPEN_EXISTING = 3
    _REPARSE = 0x400
    _DIRECTORY = 0x10
    _DEVICE = 0x40
    _OPEN_REPARSE = 0x00200000
    _BACKUP_SEMANTICS = 0x02000000
    _SHARE_READ, _SHARE_WRITE = 1, 2
    _READ_ATTRIBUTES, _GENERIC_READ = 0x80, 0x80000000
    _FILE_TYPE_DISK = 1


def _relative_parts(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 1024:
        raise GuardedReadError('Некорректный относительный путь файла')
    parts = re.split(r'[/\\]', relative)
    if (PureWindowsPath(relative).is_absolute() or PureWindowsPath(relative).drive or len(parts) > 64 or
            any(not p or p in ('.', '..') or p.endswith((' ', '.')) or
                any(ord(c) < 32 or c in '<>:"|?*' for c in p) for p in parts)):
        raise GuardedReadError('Недопустимый относительный путь файла')
    return parts


def _open_handle(path, *, directory):
    flags = _OPEN_REPARSE | (_BACKUP_SEMANTICS if directory else 0)
    access = _READ_ATTRIBUTES if directory else _GENERIC_READ
    share = _SHARE_READ | (_SHARE_WRITE if directory else 0)
    handle = _kernel.CreateFileW(str(path), access, share, None, _OPEN_EXISTING, flags, None)
    if handle == _INVALID:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _FileInfo()
        if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if (_kernel.GetFileType(handle) != _FILE_TYPE_DISK or info.attributes & (_REPARSE | _DEVICE) or
                bool(info.attributes & _DIRECTORY) != directory or (not directory and info.links != 1)):
            raise GuardedReadError('Ссылки, reparse points, жёсткие ссылки и специальные файлы не поддерживаются')
        return handle
    except BaseException:
        _kernel.CloseHandle(handle)
        raise


def _fixed_ntfs(anchor):
    if _kernel.GetDriveTypeW(anchor) != 3:
        raise GuardedReadUnsupported('Поддерживаются только локальные фиксированные диски NTFS')
    filesystem = ctypes.create_unicode_buffer(256)
    if not _kernel.GetVolumeInformationW(anchor, None, 0, None, None, None, filesystem, len(filesystem)):
        raise ctypes.WinError(ctypes.get_last_error())
    if filesystem.value.upper() != 'NTFS':
        raise GuardedReadUnsupported('Поддерживаются только локальные фиксированные диски NTFS')


class GuardedFile:
    """A readable stream retaining handles for each ancestor until closed."""
    def __init__(self, stream, directories):
        self._stream, self._directories = stream, directories

    def read(self, size=65536):
        if type(size) is not int or not 0 <= size <= 1024 * 1024:
            raise GuardedReadError('Размер чтения должен быть от 0 до 1 МиБ')
        return self._stream.read(size)

    def close(self):
        try:
            self._stream.close()
        finally:
            while self._directories:
                _kernel.CloseHandle(self._directories.pop())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def open_guarded_file(root, relative):
    """Read one file under a locked directory chain. Windows NTFS only."""
    if os.name != 'nt':
        raise GuardedReadUnsupported('Защищённое чтение пока доступно только на Windows NTFS')
    parts = _relative_parts(relative)
    if not isinstance(root, str) or not root or len(root) > 1024 or '..' in re.split(r'[/\\]', root):
        raise GuardedReadError('Некорректный корень папки игры')
    top = Path(root)
    if not top.is_absolute() or not re.fullmatch(r'[A-Za-z]:\\', top.anchor) or len(top.parts) > 64:
        raise GuardedReadError('Требуется абсолютный путь на локальном диске')
    for component in top.parts[1:]:
        _relative_parts(component)
    _fixed_ntfs(top.anchor)
    directories = []
    try:
        current = Path(top.anchor)
        directories.append(_open_handle(current, directory=True))
        for part in (*top.parts[1:], *parts[:-1]):
            current = current / part
            directories.append(_open_handle(current, directory=True))
        handle = _open_handle(current / parts[-1], directory=False)
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            _kernel.CloseHandle(handle)
            raise
        try:
            stream = os.fdopen(fd, 'rb')
        except BaseException:
            os.close(fd)
            raise
        return GuardedFile(stream, directories)
    except BaseException:
        while directories:
            _kernel.CloseHandle(directories.pop())
        raise
