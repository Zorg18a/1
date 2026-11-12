"""Experimental Windows NTFS name pin for an already-created snapshot file.

The caller must keep the guarded directory and original fd open through pinning.
The pin permits writes and does not validate ACLs, SQLite, sidecars, or durability.
It is not connected to the application or the backup coordinator.
"""
import os

from storage import guarded_read, windows_relative

if os.name == 'nt':
    import ctypes
    import msvcrt


def _identity(handle):
    info = guarded_read._FileInfo()
    if not guarded_read._kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.volume, info.index_high, info.index_low


class PinnedFile:
    def __init__(self, handle):
        self._handle = handle

    def close(self):
        if self._handle is not None:
            guarded_read._kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def pin_created_file(directory, name, fd):
    """Pin a file only if it is still the same object as the caller's open fd."""
    if os.name != 'nt':
        raise guarded_read.GuardedReadUnsupported('Защищённый файл доступен только на Windows NTFS')
    if not isinstance(directory, guarded_read.GuardedDirectory) or not directory._directories:
        raise guarded_read.GuardedReadError('Каталог должен оставаться открытым')
    if len(guarded_read._relative_parts(name)) != 1 or type(fd) is not int or fd < 0:
        raise guarded_read.GuardedReadError('Некорректное имя или дескриптор файла')
    original = msvcrt.get_osfhandle(fd)
    handle = windows_relative.open_relative(directory._directories[-1], name, directory=False, shared_write=True)
    handle = guarded_read._check_handle(handle, directory=False)
    try:
        if _identity(original) != _identity(handle):
            raise guarded_read.GuardedReadError('Файл изменился при открытии')
        return PinnedFile(handle)
    except BaseException:
        guarded_read._kernel.CloseHandle(handle)
        raise
