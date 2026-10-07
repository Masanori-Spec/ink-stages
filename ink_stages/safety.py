"""Bounded reads and fresh writes. Linux only; no best-effort safety fallbacks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from dataclasses import dataclass


class InkStagesError(ValueError):
    """An input, profile, or execution requirement was not satisfied."""


def fail(message: str):
    raise InkStagesError(message)


def absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def open_parent(path: str | Path) -> tuple[int, str, Path]:
    """Walk every parent with O_NOFOLLOW, including when supplied by the user."""
    path = absolute(path)
    if path == Path("/"):
        fail("A file path is required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, path.name, path
    except OSError as exc:
        os.close(fd)
        raise InkStagesError(f"Unsafe or inaccessible parent directory: {path.parent}: {exc.strerror}") from exc


@dataclass(frozen=True)
class Snapshot:
    path: Path
    data: bytes
    sha256: str
    device: int
    inode: int

    def summary(self) -> dict:
        return {"path": str(self.path), "bytes": len(self.data), "sha256": self.sha256}


def read_regular(path: str | Path, limit: int) -> Snapshot:
    parent, name, path = open_parent(path)
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            fail(f"Expected a regular file: {path}")
        if before.st_size > limit:
            fail(f"File exceeds {limit} byte limit: {path}")
        chunks = []
        count = 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
            if count > limit:
                fail(f"File exceeds {limit} byte limit: {path}")
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
            fail(f"Input changed while being read: {path}")
        data = b"".join(chunks)
        return Snapshot(path, data, hashlib.sha256(data).hexdigest(), before.st_dev, before.st_ino)
    except OSError as exc:
        raise InkStagesError(f"Cannot safely read {path}: {exc.strerror}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def assert_unchanged(snapshot: Snapshot, limit: int) -> dict:
    current = read_regular(snapshot.path, limit)
    if (current.device, current.inode, current.sha256) != (snapshot.device, snapshot.inode, snapshot.sha256):
        fail(f"Input changed since inspection: {snapshot.path}")
    return current.summary()


class FreshFile:
    """Reserve a new inode; never truncate or replace any preexisting file."""

    def __init__(self, path: str | Path):
        self.parent, self.name, self.path = open_parent(path)
        self.fd = None
        self.committed = False
        try:
            self.fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                              0o600, dir_fd=self.parent)
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
        except OSError as exc:
            os.close(self.parent)
            raise InkStagesError(f"Destination must be a fresh file: {self.path}: {exc.strerror}") from exc

    def _owns_path(self) -> bool:
        try:
            info = os.stat(self.name, dir_fd=self.parent, follow_symlinks=False)
            return (info.st_dev, info.st_ino) == self.identity and stat.S_ISREG(info.st_mode)
        except FileNotFoundError:
            return False

    def write(self, data: bytes):
        if self.committed or not self._owns_path():
            fail(f"Destination was replaced or already written: {self.path}")
        view = memoryview(data)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]
        os.fsync(self.fd)
        if not self._owns_path():
            fail(f"Destination changed during write: {self.path}")
        self.committed = True

    def close(self):
        if self.fd is not None:
            if not self.committed and self._owns_path():
                os.unlink(self.name, dir_fd=self.parent)
            os.close(self.fd)
            os.close(self.parent)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
