#!/usr/bin/env python3
"""Pack Git-selected files as Base64-encoded ZIP text, or unpack safely.

Usage:
    python bundle.py pack [--no-git] [FOLDER] [OUTPUT]
    python bundle.py unpack FILE [FOLDER]

By default, packing requires FOLDER to reside in a Git worktree, and Git selects
tracked files and non-ignored untracked files. With --no-git, all non-symlink
regular files below FOLDER are selected instead. Only Python's standard library
is required.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import io
import os
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

DEFAULT_OUTPUT = "bundle.zip.b64"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class BundleError(Exception):
    """Expected command failure."""


def _run_git(arguments: list[str], cwd: Path) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise BundleError("Git is required but was not found") from error
    except OSError as error:
        raise BundleError(f"could not run Git: {error}") from error

    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise BundleError(f"Git command failed{suffix}")
    return completed.stdout


def _git_worktree(folder: Path) -> Path:
    output = _run_git(["rev-parse", "--show-toplevel"], folder)
    try:
        worktree = Path(os.fsdecode(output.rstrip(b"\r\n"))).resolve(strict=True)
    except (OSError, ValueError) as error:
        raise BundleError("Git returned an invalid worktree path") from error
    if not worktree.is_dir():
        raise BundleError(f"Git worktree does not exist: {worktree}")
    try:
        folder.relative_to(worktree)
    except ValueError as error:
        raise BundleError(
            f"source folder is outside the Git worktree: {folder}"
        ) from error
    return worktree


def _filesystem_files(folder: Path, output: Path):
    """Yield all non-symlink regular files below folder without using Git."""
    selected: list[tuple[str, Path]] = []

    for directory, directory_names, file_names in os.walk(
        folder,
        followlinks=False,
    ):
        current = Path(directory)

        directory_names[:] = [
            name
            for name in directory_names
            if not (current / name).is_symlink()
        ]

        for name in file_names:
            candidate = current / name

            if candidate.is_symlink() or not candidate.is_file():
                continue

            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise BundleError(
                    f"cannot resolve selected path {candidate}: {error}"
                ) from error

            if resolved == output:
                continue

            try:
                relative = resolved.relative_to(folder)
            except ValueError as error:
                raise BundleError(
                    f"selected path escapes the source folder: {candidate}"
                ) from error

            archive_name = relative.as_posix()
            if archive_name not in ("", "."):
                selected.append((archive_name, candidate))

    yield from sorted(
        selected,
        key=lambda item: os.fsencode(item[0]),
    )


def _selected_files(folder: Path, output: Path):
    """Yield Git-selected, non-symlink regular files below folder."""
    worktree = _git_worktree(folder)
    raw = _run_git(
        ["ls-files", "-co", "--exclude-standard", "-z"],
        worktree,
    )
    names = raw.split(b"\0")
    if names and names[-1] == b"":
        names.pop()

    selected: list[tuple[str, Path]] = []
    seen: set[str] = set()

    for encoded_name in names:
        if not encoded_name:
            raise BundleError("Git returned an empty path")

        name = os.fsdecode(encoded_name)
        git_relative = Path(name)
        candidate = worktree / git_relative

        try:
            source_relative = candidate.relative_to(folder)
        except ValueError:
            continue

        archive_name = source_relative.as_posix()
        if archive_name in ("", ".") or archive_name in seen:
            continue
        seen.add(archive_name)

        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise BundleError(
                f"cannot resolve selected path {candidate}: {error}"
            ) from error

        if candidate.is_symlink() or not candidate.is_file():
            continue
        if resolved == output:
            continue

        try:
            resolved.relative_to(worktree)
        except ValueError as error:
            raise BundleError(
                f"selected path escapes the Git worktree: {candidate}"
            ) from error

        selected.append((archive_name, candidate))

    yield from sorted(
        selected,
        key=lambda item: os.fsencode(item[0]),
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_symlink():
        raise BundleError(f"refusing to replace symlink: {path}")

    temporary: str | None = None

    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )

        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def pack(
    folder: str,
    output: str,
    *,
    no_git: bool = False,
) -> None:
    root = Path(folder).expanduser().resolve()
    destination = Path(output).expanduser().resolve()

    if not root.is_dir():
        raise BundleError(
            f"source folder does not exist or is not a directory: {root}"
        )

    archive = io.BytesIO()

    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as zipped:
        selected_files = _filesystem_files if no_git else _selected_files

        for relative, source in selected_files(root, destination):
            info = zipfile.ZipInfo(
                relative,
                date_time=ZIP_TIMESTAMP,
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits |= 0x800

            try:
                data = source.read_bytes()
            except OSError as error:
                raise BundleError(
                    f"cannot read {source}: {error}"
                ) from error

            zipped.writestr(
                info,
                data,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )

    _atomic_write(
        destination,
        base64.b64encode(archive.getvalue()),
    )
    print(destination)


def _validated_members(
    zipped: zipfile.ZipFile,
    root: Path,
):
    members: list[tuple[zipfile.ZipInfo, Path]] = []
    seen: set[str] = set()

    for info in zipped.infolist():
        name = info.filename
        pure = PurePosixPath(name)
        mode = info.external_attr >> 16

        if (
            not name
            or "\\" in name
            or pure.is_absolute()
            or any(part in ("", ".", "..") for part in pure.parts)
            or (pure.parts and pure.parts[0].endswith(":"))
        ):
            raise BundleError(f"unsafe path in archive: {name!r}")

        if name in seen:
            raise BundleError(f"duplicate path in archive: {name!r}")
        seen.add(name)

        if info.is_dir():
            continue

        if mode and not stat.S_ISREG(mode):
            raise BundleError(
                f"unsupported non-regular archive member: {name!r}"
            )

        target = (root / Path(*pure.parts)).resolve()

        if target != root and root not in target.parents:
            raise BundleError(f"path escapes destination: {name!r}")

        members.append((info, target))

    return members


def unpack(source: str, folder: str) -> None:
    carrier = Path(source).expanduser().resolve()
    root = Path(folder).expanduser().resolve()

    if not carrier.is_file():
        raise BundleError(
            f"bundle does not exist or is not a file: {carrier}"
        )

    if root.exists() and not root.is_dir():
        raise BundleError(
            f"destination exists and is not a directory: {root}"
        )

    try:
        archive_bytes = base64.b64decode(
            carrier.read_bytes(),
            validate=True,
        )
    except (OSError, binascii.Error, ValueError) as error:
        raise BundleError(
            f"invalid Base64 bundle: {carrier}"
        ) from error

    try:
        with zipfile.ZipFile(
            io.BytesIO(archive_bytes),
            mode="r",
        ) as zipped:
            members = _validated_members(zipped, root)

            for _, target in members:
                if target.exists() or target.is_symlink():
                    raise BundleError(
                        f"refusing to overwrite existing path: {target}"
                    )

                parent = target.parent
                while parent != root and parent != parent.parent:
                    if parent.is_symlink():
                        raise BundleError(
                            "destination contains a symlink parent: "
                            f"{parent}"
                        )
                    parent = parent.parent

            root.mkdir(parents=True, exist_ok=True)

            for info, target in members:
                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                _atomic_write(
                    target,
                    zipped.read(info),
                )
    except zipfile.BadZipFile as error:
        raise BundleError(
            f"decoded data is not a valid ZIP archive: {carrier}"
        ) from error

    print(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pack selected files as Base64-encoded ZIP text, "
            "or unpack safely."
        )
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    pack_parser = commands.add_parser(
        "pack",
        help="pack selected files below FOLDER",
    )
    pack_parser.add_argument(
        "--no-git",
        action="store_true",
        help=(
            "pack all regular files below FOLDER without "
            "requiring a Git worktree"
        ),
    )
    pack_parser.add_argument(
        "folder",
        nargs="?",
        default=".",
        metavar="FOLDER",
    )
    pack_parser.add_argument(
        "output",
        nargs="?",
        default=DEFAULT_OUTPUT,
        metavar="OUTPUT",
    )

    unpack_parser = commands.add_parser(
        "unpack",
        help="unpack FILE into FOLDER",
    )
    unpack_parser.add_argument(
        "source",
        metavar="FILE",
    )
    unpack_parser.add_argument(
        "folder",
        nargs="?",
        default=".",
        metavar="FOLDER",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "pack":
            pack(
                arguments.folder,
                arguments.output,
                no_git=arguments.no_git,
            )
        else:
            unpack(
                arguments.source,
                arguments.folder,
            )

        return 0
    except BundleError as error:
        parser.exit(
            1,
            f"ERROR: {error}\n",
        )
    except OSError as error:
        parser.exit(
            1,
            f"ERROR: filesystem operation failed: {error}\n",
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
