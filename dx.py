#!/usr/bin/env python3
"""Canonical DX v1.3.1 codec and CLI for collaboration tooling."""
from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, TextIO

VERSION = "v1.3.1"
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


class DxError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    path: str
    data: bytes
    readonly: bool = False
    encoding: str | None = None


def safe_path(raw: str) -> str:
    value = raw.replace("\\", "/")
    parts = value.split("/")
    if (not value or value.startswith("/") or '"' in value or "\x00" in value
            or "\n" in value or "\r" in value
            or any(part in ("", ".", "..") for part in parts)):
        raise DxError(f"unsafe path: {raw!r}")
    return PurePosixPath(value).as_posix()


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def encode_text_line(line: str) -> str:
    """Apply the required four-space payload indent plus one nested-DX level."""
    return "        " + line if line.startswith("%%") else "    " + line


def decode_text_line(line: str) -> str:
    """Remove the payload indent and exactly one nested-DX escape level."""
    if not line.startswith("    "):
        raise DxError(f"unindented text payload line: {line!r}")
    line = line[4:]
    return line[4:] if line.startswith("    %%") else line


def decoded_payload(path: str, body: list[str], encoding: str | None) -> bytes:
    if encoding in (None, "", "utf-8"):
        text = "\n".join(decode_text_line(line) for line in body)
        return (text.rstrip("\n") + "\n").encode("utf-8")
    if encoding == "base64":
        try:
            return base64.b64decode("".join(line[4:] if line.startswith("    ") else line for line in body), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DxError(f"invalid base64 payload: {path}") from exc
    raise DxError(f"unsupported encoding {encoding!r}: {path}")


def parse(source: TextIO) -> tuple[str, list[Entry], int]:
    lines = source.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")
    version = "unversioned"
    entries: list[Entry] = []
    notes = 0
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("%%DX"):
            parts = line.split()
            version = parts[1] if len(parts) > 1 else "unknown"
            index += 1
            continue
        if line == "%%END":
            break
        if line.startswith("%%NOTE"):
            notes += 1
            index += 1
            while index < len(lines) and lines[index] != "%%ENDBLOCK":
                index += 1
            if index >= len(lines):
                raise DxError("unterminated NOTE block")
            index += 1
            continue
        if not line.startswith("%%FILE"):
            index += 1
            continue
        attrs = dict(ATTR_RE.findall(line))
        if "path" not in attrs:
            raise DxError(f"FILE without path at line {index + 1}")
        path = safe_path(attrs["path"])
        if path in seen:
            raise DxError(f"duplicate path: {path}")
        seen.add(path)
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index] != "%%ENDBLOCK":
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise DxError(f"unterminated file block: {path}")
        index += 1
        encoding = attrs.get("encoding")
        entries.append(Entry(path, decoded_payload(path, body, encoding),
                             attrs.get("readonly", "false").lower() == "true", encoding))
    return version, entries, notes


def read_entries(path: str) -> tuple[str, list[Entry], int]:
    if path == "-":
        return parse(sys.stdin)
    with open(path, "r", encoding="utf-8", newline="") as source:
        return parse(source)


def encode_entry(handle: TextIO, path: str, data: bytes, readonly: bool,
                 include_non_utf8: bool, omit_non_utf8: bool) -> bool:
    attrs = [f'path="{safe_path(path)}"']
    if readonly:
        attrs.append('readonly="true"')
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if not include_non_utf8:
            if omit_non_utf8:
                print(f"omit non-UTF-8 file: {path}", file=sys.stderr)
                return False
            raise DxError(f"non-UTF-8 file requires --include-non-utf8: {path}")
        attrs.append('encoding="base64"')
        handle.write("%%FILE " + " ".join(attrs) + "\n")
        handle.write("    " + base64.b64encode(data).decode("ascii") + "\n")
        handle.write("%%ENDBLOCK\n")
        return True
    handle.write("%%FILE " + " ".join(attrs) + "\n")
    text = normalize_text(text)
    if text:
        for line in text.split("\n"):
            handle.write(encode_text_line(line) + "\n")
    handle.write("%%ENDBLOCK\n")
    return True


def match_pattern(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/").removeprefix("./").rstrip("/")
    if not pattern:
        return False
    parts = PurePosixPath(path).parts
    candidates = [path] + ["/".join(parts[:i]) for i in range(1, len(parts))]
    return any(candidate == pattern or candidate.startswith(pattern + "/")
               or fnmatch.fnmatchcase(candidate, pattern)
               or ("/" not in pattern and fnmatch.fnmatchcase(PurePosixPath(candidate).name, pattern))
               for candidate in candidates)


def selected(path: str, includes: list[str], excludes: list[str]) -> bool:
    return (not includes or any(match_pattern(path, p) for p in includes)) \
        and not any(match_pattern(path, p) for p in excludes)


def git_changed_paths() -> list[str]:
    proc = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                          check=True, stdout=subprocess.PIPE)
    records = proc.stdout.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", "strict")
        status, path = text[:2], text[3:]
        if "D" in status:
            raise DxError(f"deletions cannot be represented in a DX carrier: {path}")
        if status[0] in "RC" or status[1] in "RC":
            if index >= len(records) or not records[index]:
                raise DxError(f"malformed git rename/copy record: {path}")
            path = records[index].decode("utf-8", "strict")
            index += 1
        paths.append(safe_path(path))
    return sorted(set(paths))


def collect_paths(root: Path, explicit: list[str], from_git: bool,
                  includes: list[str], excludes: list[str]) -> list[str]:
    if explicit and from_git:
        raise DxError("--path and --from-git are mutually exclusive")
    if from_git:
        names = git_changed_paths()
    elif explicit:
        names = []
        for raw in explicit:
            candidate = root / raw
            if candidate.is_dir():
                names.extend(p.relative_to(root).as_posix() for p in candidate.rglob("*") if p.is_file())
            else:
                names.append(raw)
    else:
        names = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return sorted({safe_path(name) for name in names if selected(safe_path(name), includes, excludes)})


def atomic_writer(output: Path):
    if output.is_symlink():
        raise DxError(f"refusing to replace symlink: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                       dir=output.parent, prefix=output.name + ".tmp.", delete=False)


def pack_command(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise DxError(f"not a directory: {root}")
    names = collect_paths(root, args.path, args.from_git, args.include, args.exclude)
    if not names:
        raise DxError("no files selected")
    output = Path(args.out)
    temp = atomic_writer(output)
    written = 0
    omitted = 0
    try:
        with temp as handle:
            handle.write(f"%%DX {VERSION}\n")
            for name in names:
                target = root / name
                if target.is_symlink() or not target.is_file():
                    raise DxError(f"selected path is not a regular file: {name}")
                if encode_entry(handle, name, target.read_bytes(), args.readonly,
                                args.include_non_utf8, args.omit_non_utf8):
                    written += 1
                else:
                    omitted += 1
            if not written:
                raise DxError("no representable files selected")
            handle.write("%%END\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp.name, output)
    except Exception:
        Path(temp.name).unlink(missing_ok=True)
        raise
    print(output)
    if omitted:
        print(f"omitted non-UTF-8 files: {omitted}", file=sys.stderr)
    return 0


def apply_command(args: argparse.Namespace) -> int:
    _, entries, _ = read_entries(args.carrier)
    root = Path(args.destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry.readonly:
            continue
        target = (root / Path(*PurePosixPath(entry.path).parts)).resolve()
        if target != root and root not in target.parents:
            raise DxError(f"path escapes destination: {entry.path}")
        if target.exists() and not args.force:
            print(f"skip existing: {entry.path}", file=sys.stderr)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.data)
    return 0


def inspect_command(args: argparse.Namespace) -> int:
    version, entries, notes = read_entries(args.carrier)
    if args.list:
        for entry in entries:
            print(entry.path)
    elif args.hashes:
        for entry in entries:
            print(f"{hashlib.sha256(entry.data).hexdigest()} {entry.path}")
    elif args.readonly:
        for entry in entries:
            if entry.readonly:
                print(entry.path)
    elif args.file is not None:
        matches = [entry for entry in entries if entry.path == args.file]
        if len(matches) != 1:
            raise DxError(f"expected exactly one file named {args.file!r}, found {len(matches)}")
        sys.stdout.buffer.write(matches[0].data)
    elif args.compare_root is not None:
        root = Path(args.compare_root).resolve()
        mismatches = 0
        for entry in entries:
            target = root / Path(*PurePosixPath(entry.path).parts)
            if not target.is_file() or target.read_bytes() != entry.data:
                print(entry.path)
                mismatches += 1
        return 1 if mismatches else 0
    else:
        print(f"DX version: {version}")
        print(f"File count: {len(entries)}")
        print(f"NOTE blocks: {notes}")
        for entry in entries:
            print(f"{entry.path}\treadonly={'true' if entry.readonly else 'false'}\tsha256={hashlib.sha256(entry.data).hexdigest()}")
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="dx.py")
    sub = top.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--out", required=True)
    pack.add_argument("--root", default=".")
    pack.add_argument("--path", action="append", default=[])
    pack.add_argument("--from-git", action="store_true")
    pack.add_argument("--include", action="append", default=[])
    pack.add_argument("--exclude", action="append", default=[])
    pack.add_argument("--include-non-utf8", action="store_true")
    pack.add_argument("--omit-non-utf8", action="store_true")
    pack.add_argument("--readonly", action="store_true")
    pack.set_defaults(func=pack_command)
    for name in ("unpack", "apply"):
        apply = sub.add_parser(name)
        apply.add_argument("carrier")
        apply.add_argument("destination", nargs="?", default=".")
        apply.add_argument("-f", "--force", action="store_true")
        apply.set_defaults(func=apply_command)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("carrier")
    mode = inspect.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--hashes", action="store_true")
    mode.add_argument("--readonly", action="store_true")
    mode.add_argument("--file")
    mode.add_argument("--compare-root")
    inspect.set_defaults(func=inspect_command)
    return top


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return args.func(args)
    except (DxError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
