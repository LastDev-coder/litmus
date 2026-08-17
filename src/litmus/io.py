"""Safe, atomic output writing.

A transformation tool rewrites files the user cares about, so the write path
is a security boundary, not a convenience. Three rules:

* **Refuse symlinks.** Following a symlink lets a crafted tree redirect a write
  outside its intended target. We refuse rather than resolve.
* **Write atomically.** A temp file in the same directory, then ``os.replace``.
  A crash mid-write leaves the original intact rather than a truncated file.
* **Back up on request.** ``--backup`` copies the original to ``<name>.bak``
  before replacing it.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class SafeWriteError(Exception):
    """Raised when a write is refused for a safety reason."""


def safe_write(path: Path, data: bytes, *, backup: bool = False) -> None:
    """Atomically write ``data`` to ``path``, refusing to follow a symlink.

    ``os.path.islink`` is checked (not ``Path.is_symlink`` after resolution) so
    that a symlink at the destination is detected before anything is written.
    """
    if os.path.islink(path):
        raise SafeWriteError(f"refusing to write through a symlink: {path}")

    parent = path.parent
    if not parent.exists():
        raise SafeWriteError(f"parent directory does not exist: {parent}")

    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))

    # Temp file in the same directory guarantees os.replace is a rename, not a
    # cross-filesystem copy (which would not be atomic).
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
