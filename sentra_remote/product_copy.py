"""Replace owned product files without changing directory ACLs or user data."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar

from .windows_paths import filesystem_path, resolved_path

_clean_guard = ContextVar('sentra_clean_copy_guard', default=False)


@contextmanager
def protect_clean_targets():
    """Fail rather than overwrite a file created after clean preflight."""
    token = _clean_guard.set(True)
    try:
        yield
    finally:
        _clean_guard.reset(token)


def _ordinary_path(path):
    value = str(Path(path).absolute())
    if os.name == 'nt' and value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif os.name == 'nt' and value.startswith('\\\\?\\'):
        value = value[4:]
    return Path(value)


def open_product_target(path, *, root, encoding=None):
    """Use exclusive creation and reject changed directory links for clean copies."""
    path = _ordinary_path(path)
    if _clean_guard.get():
        owner = resolved_path(root)
        try:
            relative = path.relative_to(owner)
        except ValueError as exc:
            raise ValueError('product copy target escaped installation') from exc
        current = owner
        for part in relative.parts:
            current = current / part
            disk = Path(filesystem_path(current, resolve=False))
            if disk.is_symlink() or (hasattr(disk, 'is_junction') and disk.is_junction()):
                raise ValueError('linked product copy target')
        mode = 'x' if encoding else 'xb'
    else:
        mode = 'w' if encoding else 'wb'
    disk = filesystem_path(path, resolve=False)
    return open(disk, mode, encoding=encoding) if encoding else open(disk, mode)


def copy_product_file(source, destination, *, root: Path):
    target = Path(destination)
    owner = resolved_path(root)
    # Resolve parents only: following an existing target link would hide it.
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('linked product copy target')
    if not resolved_path(target.parent).is_relative_to(owner):
        raise ValueError('product copy target escaped installation')
    disk = filesystem_path(target, resolve=False)
    if _clean_guard.get():
        # Exclusive creation closes the preflight/copy race. shutil.copy2
        # alone would silently replace a newly created unrelated file.
        with open(source, 'rb') as src, open_product_target(target, root=root) as dst:
            shutil.copyfileobj(src, dst)
        shutil.copystat(source, disk)
        return str(destination)
    try:
        return shutil.copy2(source, disk)
    except PermissionError:
        # A locked executable, denied ACL or writable file is never retried.
        info = os.stat(disk, follow_symlinks=False)
        readonly = os.name == 'nt' and bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
        if not readonly or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise
        descriptor, temporary = tempfile.mkstemp(prefix='.sentra-copy-', dir=filesystem_path(target.parent))
        os.close(descriptor)
        cleared = False
        try:
            shutil.copy2(source, temporary)
            os.chmod(disk, info.st_mode | stat.S_IWRITE)
            cleared = True
            os.replace(temporary, disk)
            cleared = False
            return str(destination)
        finally:
            if cleared:
                os.chmod(disk, info.st_mode)
            if os.path.exists(temporary):
                os.chmod(temporary, stat.S_IREAD | stat.S_IWRITE)
                os.unlink(temporary)
