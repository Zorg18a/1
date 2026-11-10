"""Legacy file removal policy. Paths must be trusted and confirmed by the caller.

This is not a secure path sandbox or an atomic transaction. In particular, a
failure can occur after earlier files have already been removed.
"""
from pathlib import Path
import shutil


def remove_files(row):
    if row['root']:
        shutil.rmtree(row['root'])
        return
    path = Path(row['path'])
    for entry in list(path.parent.iterdir()):
        if entry.stem == path.stem or entry.name.startswith(path.stem + '.'):
            entry.unlink()
