"""Small owner-local atomic file primitives used by configuration state."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import BinaryIO, Iterator


@contextmanager
def open_owner_binary(path: Path, *, max_bytes: int, allow_empty: bool = False) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Open one bounded owner-local regular file without following a leaf symlink."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    handle: BinaryIO | None = None
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise OSError(errno.EINVAL, "owner-local state is not a regular file", str(path))
        if details.st_uid != os.geteuid():
            raise PermissionError(errno.EPERM, "owner-local state has a different owner", str(path))
        if details.st_size < 0 or (details.st_size == 0 and not allow_empty) or details.st_size > max_bytes:
            raise ValueError(f"owner-local state must be between {1 if not allow_empty else 0} and {max_bytes} bytes")
        handle = os.fdopen(fd, "rb")
        fd = -1
        yield handle, details
    finally:
        if handle is not None:
            handle.close()
        elif fd >= 0:
            os.close(fd)


def read_owner_text(path: Path, *, max_bytes: int = 1024 * 1024) -> str:
    """Read one regular owner-local UTF-8 file without following a leaf symlink."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise OSError(errno.EINVAL, "owner-local state is not a regular file", str(path))
        if details.st_uid != os.geteuid():
            raise PermissionError(errno.EPERM, "owner-local state has a different owner", str(path))
        if details.st_size > max_bytes:
            raise ValueError(f"owner-local state exceeds {max_bytes} bytes")
        chunks = bytearray()
        while len(chunks) <= max_bytes:
            chunk = os.read(fd, min(65536, max_bytes + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise ValueError(f"owner-local state exceeds {max_bytes} bytes")
        return bytes(chunks).decode("utf-8")
    finally:
        os.close(fd)


def atomic_write(path: Path, data: str | bytes, *, mode: int = 0o600) -> None:
    """Durably replace ``path`` without ever exposing a partial destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        os.fchmod(fd, mode)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        # Persist the directory entry where the filesystem supports it.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def exclusive_file_lock(path: Path, *, timeout: float | None = None) -> Iterator[None]:
    """Serialize updates across threads/processes, with an optional wait bound."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise PermissionError("unsafe configuration lock file")
        if timeout is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + max(0.0, float(timeout))
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timed out waiting for the owner-local operation lock")
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
