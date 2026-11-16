"""Safe and durable filesystem operations."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, IO

class FilesystemError(OSError):
    pass

def reject_symlink(path: Path, *, description: str = "path") -> None:
    if path.is_symlink():
        raise FilesystemError(f"refusing unsafe symlink {description}: {path}")

def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None, replace: bool = True) -> None:
    def writer(handle: IO[bytes]) -> None:
        handle.write(data)
    atomic_write(path, writer, mode=mode, replace=replace, binary=True)

def atomic_write_text(path: Path, writer: Callable[[IO[str]], None], *, replace: bool = True, encoding: str = "utf-8") -> None:
    atomic_write(path, writer, replace=replace, binary=False, encoding=encoding)

def atomic_write(path: Path, writer, *, mode: int | None = None, replace: bool = True, binary: bool = True, encoding: str = "utf-8") -> None:
    reject_symlink(path, description="target")
    if path.exists() and not replace:
        raise FilesystemError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink(path.parent, description="parent")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        open_kwargs = {} if binary else {"encoding": encoding, "newline": "\n"}
        with os.fdopen(fd, "wb" if binary else "w", **open_kwargs) as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and path.exists():
            raise FilesystemError(f"output already exists: {path}")
        os.replace(temporary, path)
        if mode is not None:
            try: os.chmod(path, mode)
            except OSError: pass
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def write_text_atomic(path: Path, value: str, *, replace: bool = True) -> None:
    """Write one UTF-8/LF text value atomically."""
    atomic_write_text(path, lambda stream: stream.write(value), replace=replace)

def write_json_atomic(path: Path, value: object, *, replace: bool = True) -> None:
    """Write deterministic UTF-8 JSON atomically."""
    import json
    payload=json.dumps(value,indent=2,ensure_ascii=False,sort_keys=True)+"\n"
    write_text_atomic(path,payload,replace=replace)
