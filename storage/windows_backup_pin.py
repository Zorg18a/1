"""Experimental Windows NTFS name pin for an already-created snapshot file.

The caller must keep the guarded directory and original fd open through pinning.
The pin permits writes and does not validate ACLs, SQLite, sidecars, or durability.
It is used only by the isolated guarded snapshot path, not the application.
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


def pin_existing_file(directory, name):
    """Pin one existing regular file; the caller must keep directory open."""
    if os.name != 'nt':
        raise guarded_read.GuardedReadUnsupported('Защищённый файл доступен только на Windows NTFS')
    if not isinstance(directory, guarded_read.GuardedDirectory) or not directory._directories:
        raise guarded_read.GuardedReadError('Каталог должен оставаться открытым')
    if len(guarded_read._relative_parts(name)) != 1:
        raise guarded_read.GuardedReadError('Некорректное имя файла')
    handle = windows_relative.open_relative(directory._directories[-1], name, directory=False, shared_write=True)
    return PinnedFile(guarded_read._check_handle(handle, directory=False))


def pin_created_file(directory, name, fd):
    """Pin a file only if it is still the same object as the caller's open fd."""
    if os.name != 'nt':
        raise guarded_read.GuardedReadUnsupported('Защищённый файл доступен только на Windows NTFS')
    if type(fd) is not int or fd < 0:
        raise guarded_read.GuardedReadError('Некорректный дескриптор файла')
    original = msvcrt.get_osfhandle(fd)
    pin = pin_existing_file(directory, name)
    try:
        if _identity(original) != _identity(pin._handle):
            raise guarded_read.GuardedReadError('Файл изменился при открытии')
        return pin
    except BaseException:
        pin.close()
        raise
