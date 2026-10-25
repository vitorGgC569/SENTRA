"""Replace owned product files without changing directory ACLs or user data."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile

from .windows_paths import filesystem_path, resolved_path


def copy_product_file(source, destination, *, root: Path):
    target = Path(destination)
    owner = resolved_path(root)
    # Resolve parents only: following an existing target link would hide it.
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise ValueError('linked product copy target')
    if not resolved_path(target.parent).is_relative_to(owner):
        raise ValueError('product copy target escaped installation')
    disk = filesystem_path(target, resolve=False)
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
