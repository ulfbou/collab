#!/usr/bin/env python3
"""
DX v2.0.0 carrier codec and CLI.

A deterministic, safe, and user-friendly CLI for packing, unpacking, and
inspecting DX carrier files.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, TextIO, Iterable, List, Dict, Any

try:
    from collab.filesystem import FilesystemError, atomic_write_text
    from collab.validation import ValidationError, require_safe_relative_path
except ModuleNotFoundError:
    # Standalone fallback (same as original)
    import tempfile as _tempfile
    class FilesystemError(OSError):
        pass
    class ValidationError(ValueError):
        pass

    def require_safe_relative_path(value: str, location: str = "path") -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (not normalized or normalized.startswith("/") or '"' in normalized or "\0" in normalized or "\n" in normalized or "\r" in normalized or any(part in ("", ".", "..") for part in parts)):
            raise ValidationError(f"unsafe {location}: {value!r}")
        return PurePosixPath(normalized).as_posix()

    def atomic_write_text(path: Path, writer, *, replace: bool = True, encoding: str = "utf-8"):
        if path.is_symlink():
            raise FilesystemError(f"refusing unsafe symlink target: {path}")
        if path.exists() and not replace:
            raise FilesystemError(f"output already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = _tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
        os.close(fd)
        try:
            with open(tmp, "w", encoding=encoding, newline="\n") as h:
                writer(h)
                h.flush()
                os.fsync(h.fileno())
            if not replace and path.exists():
                raise FilesystemError(f"output already exists: {path}")
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


VERSION = "v2.0.0"
DX_FORMAT = "v2.0"
DEFAULT_DEVICE_DIR = Path("~/storage/downloads/DX").expanduser()

ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
NUMBERED_RE = re.compile(r'^dx-carrier-(\d+)\.dx\.txt$')


class DxError(ValueError):
    """Base class for operational errors."""
    exit_code = 2  # default usage error

class UsageError(DxError):
    exit_code = 2

class InvalidCarrierError(DxError):
    exit_code = 3

class IOErrorDx(DxError):
    exit_code = 4

class WriteConflictError(DxError):
    exit_code = 5

class VerifyError(DxError):
    exit_code = 6


@dataclass(frozen=True)
class Entry:
    path: str
    data: bytes
    readonly: bool = False
    encoding: str | None = None
    escaped: bool = False


def safe_path(raw: str) -> str:
    try:
        return require_safe_relative_path(raw)
    except ValidationError as exc:
        raise UsageError(f"unsafe path: {raw!r}") from exc


def normalize_text(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')


def encode_text_line(line: str) -> str:
    # v2: escape lines starting with %% by adding 4 extra spaces.
    return ('        ' if line.startswith('%%') else '    ') + line


def decode_text_line(line: str, escaped: bool) -> str:
    if not line.startswith('    '):
        raise InvalidCarrierError(f"unindented text payload line: {line!r}")
    line = line[4:]
    if escaped and line.startswith('    %%'):
        # Remove the extra four spaces used for escaping.
        return line[4:]
    return line


def decoded_payload(path: str, body: list[str], encoding: str | None, escaped: bool) -> bytes:
    if encoding in (None, ''):
        text = '\n'.join(decode_text_line(x, escaped) for x in body)
        return (text.rstrip('\n') + '\n').encode('utf-8')
    if encoding == 'base64':
        try:
            chunks = []
            for line in body:
                if not line.startswith('    '):
                    raise InvalidCarrierError(f"unindented base64 payload line: {path}")
                chunks.append(line[4:])
            return base64.b64decode(''.join(chunks), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidCarrierError(f"invalid base64 payload: {path}") from exc
    raise InvalidCarrierError(f"unsupported encoding {encoding!r}: {path}")


def parse(source: TextIO) -> tuple[str, list[Entry], int]:
    """Parse a DX carrier stream.
    Returns (version, entries, note_blocks)."""
    lines = source.read().replace('\r\n', '\n').replace('\r', '\n').split('\n')
    version = 'unversioned'
    entries = []
    notes = 0
    seen = set()
    i = 0
    found_dx_header = False
    found_end = False

    while i < len(lines):
        line = lines[i]
        if line.startswith('%%DX'):
            if found_dx_header:
                raise InvalidCarrierError("multiple %%DX headers")
            found_dx_header = True
            parts = line.split()
            version = parts[1] if len(parts) > 1 else 'unknown'
            if version not in ('v1.3.1', 'v2.0.0'):
                raise InvalidCarrierError(f"unsupported DX version: {version}")
            i += 1
            continue
        if line == '%%END':
            found_end = True
            break
        if line.startswith('%%NOTE'):
            notes += 1
            i += 1
            while i < len(lines) and lines[i] != '%%ENDBLOCK':
                i += 1
            if i >= len(lines):
                raise InvalidCarrierError('unterminated NOTE block')
            i += 1
            continue
        if line.startswith('%%FILE'):
            attrs = dict(ATTR_RE.findall(line))
            if 'path' not in attrs:
                raise InvalidCarrierError(f"FILE without path at line {i+1}")
            path = safe_path(attrs['path'])
            if path in seen:
                raise InvalidCarrierError(f"duplicate path: {path}")
            seen.add(path)
            i += 1
            body = []
            while i < len(lines) and lines[i] != '%%ENDBLOCK':
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise InvalidCarrierError(f"unterminated file block: {path}")
            enc = attrs.get('encoding')
            escaped = attrs.get('escaped', 'false').lower() == 'true'
            if version != 'v2.0.0':
                # legacy: always assume escaped behavior (indentation-based)
                escaped = True
            entries.append(Entry(
                path,
                decoded_payload(path, body, enc, escaped),
                attrs.get('readonly', 'false').lower() == 'true',
                enc,
                escaped
            ))
            i += 1
            continue
        if line:
            raise InvalidCarrierError(f"unexpected line {i+1}: {line}")
        i += 1

    if not found_dx_header:
        raise InvalidCarrierError("missing %%DX header")
    if not found_end:
        raise InvalidCarrierError("missing %%END")
    return version, entries, notes


def read_entries(path: str) -> tuple[str, list[Entry], int]:
    if path == '-':
        return parse(sys.stdin)
    p = Path(path)
    if not p.is_file():
        raise IOErrorDx(f"carrier does not exist: {path}")
    with p.open('r', encoding='utf-8', newline='') as f:
        return parse(f)


# ------------------------- Filtering and collection -------------------------

def match_pattern(path: str, pattern: str) -> bool:
    pattern = pattern.replace('\\', '/').removeprefix('./').rstrip('/')
    if not pattern:
        return False
    prefixes = [path] + ['/'.join(PurePosixPath(path).parts[:i]) for i in range(1, len(PurePosixPath(path).parts))]
    return any(x == pattern or x.startswith(pattern + '/') or fnmatch.fnmatchcase(x, pattern) or ('/' not in pattern and fnmatch.fnmatchcase(PurePosixPath(x).name, pattern)) for x in prefixes)


def selected(path: str, includes: list[str], excludes: list[str]) -> bool:
    # Explicit exclusion wins over inclusion.
    if any(match_pattern(path, x) for x in excludes):
        return False
    if includes and not any(match_pattern(path, x) for x in includes):
        return False
    return True


def normalize_extension(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        raise UsageError('extension must not be empty')
    if '/' in value or '\\' in value or any(ch in value for ch in ('\0', '\n', '\r')):
        raise UsageError(f"invalid extension: {raw!r}")
    # Ensure leading dot
    if not value.startswith('.'):
        value = '.' + value
    return value


def matches_compound_extension(filename: str, ext: str) -> bool:
    """Check if filename ends with given extension (e.g., '.tar.gz')."""
    return filename.lower().endswith(ext)


def extension_selected(path: str, include_extensions: list[str], exclude_extensions: list[str]) -> bool:
    basename = PurePosixPath(path).name.lower()
    exclude_set = {normalize_extension(value) for value in exclude_extensions}
    include_set = {normalize_extension(value) for value in include_extensions}

    # Exclude if matches any exclude extension.
    for ext in exclude_set:
        if matches_compound_extension(basename, ext):
            return False

    # If includes provided, must match at least one.
    if include_set:
        for ext in include_set:
            if matches_compound_extension(basename, ext):
                return True
        return False

    return True


def git_changed_paths(root: Path) -> list[str]:
    """Return list of paths changed according to git status (no deletions)."""
    p = subprocess.run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                       cwd=root, check=True, stdout=subprocess.PIPE)
    rec = p.stdout.split(b'\0')
    out = []
    i = 0
    while i < len(rec):
        r = rec[i]
        i += 1
        if not r:
            continue
        s = r.decode('utf-8', 'strict')
        status, path = s[:2], s[3:]
        if 'D' in status:
            raise UsageError(f"deletions cannot be represented in a DX carrier: {path}")
        if status[0] in 'RC' or status[1] in 'RC':
            if i >= len(rec) or not rec[i]:
                raise UsageError(f"malformed git rename/copy record: {path}")
            path = rec[i].decode('utf-8', 'strict')
            i += 1
        out.append(safe_path(path))
    return sorted(set(out))


def get_git_allowed_paths(root: Path) -> Optional[set[str]]:
    """Get set of relative paths that are tracked or untracked but not ignored."""
    try:
        p = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
        )
        if p.returncode != 0:
            return None  # not a git repo or error
        paths = set()
        for line in p.stdout.split(b'\n'):
            if line:
                rel = line.decode('utf-8', 'strict').replace('\\', '/')
                paths.add(rel)
        return paths
    except (FileNotFoundError, UnicodeDecodeError):
        return None


def apply_gitignore_filter(source: Path, candidates: set[str]) -> set[str]:
    """Return subset of candidates that are not git-ignored untracked files."""
    if not candidates:
        return candidates
    # Find git root
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False
        )
        if probe.returncode != 0:
            return candidates  # not in git repo
        repo_root = Path(probe.stdout.strip()).resolve()
    except FileNotFoundError:
        return candidates

    allowed = get_git_allowed_paths(repo_root)
    if allowed is None:
        return candidates  # fallback: no filtering

    # Convert candidate paths to relative to repo_root
    filtered = set()
    for name in candidates:
        abs_path = (source / Path(*PurePosixPath(name).parts)).resolve()
        try:
            rel_to_repo = abs_path.relative_to(repo_root).as_posix()
        except ValueError:
            # outside repo, keep
            filtered.add(name)
            continue
        if rel_to_repo in allowed:
            filtered.add(name)
    return filtered


DEFAULT_EXCLUDES = ['.git', '.DS_Store', 'Thumbs.db']


def collect_paths(root: Path, source: Path, explicit: list[str], from_git: bool,
                  includes: list[str], excludes: list[str],
                  include_extensions: list[str], exclude_extensions: list[str],
                  output: Optional[Path], device: bool,
                  no_gitignore: bool = False, no_default_excludes: bool = False) -> list[str]:
    if explicit and from_git:
        raise UsageError('--path and --from-git are mutually exclusive')

    if from_git:
        names = git_changed_paths(root)
    elif explicit:
        names = []
        for raw in explicit:
            c = root / raw
            if not c.exists():
                raise IOErrorDx(f"selected path does not exist: {raw}")
            if c.is_dir():
                names += [p.relative_to(root).as_posix() for p in c.rglob('*') if p.is_file()]
            else:
                names.append(c.relative_to(root).as_posix())
    else:
        # Walk source (directory or single file)
        if source.is_file():
            names = [source.name] if source.parent == root else [source.relative_to(root).as_posix()]
        else:
            names = []
            for directory, child_dirs, files in os.walk(source, topdown=True, followlinks=False):
                current = Path(directory)
                child_dirs[:] = sorted(name for name in child_dirs if name != '.git' and not (current / name).is_symlink())
                for name in sorted(files):
                    candidate = current / name
                    if candidate.is_file() and not candidate.is_symlink():
                        names.append(candidate.relative_to(source).as_posix())

    # Normalize to set for filtering
    result = set(names)

    # Self-exclusion (output path)
    output_resolved = output.resolve() if output and output != Path('-') else None
    if output_resolved:
        result = {n for n in result if (root / n).resolve() != output_resolved}

    # Protected safety exclusions (always exclude .git and default excludes unless explicitly overridden)
    protected = {'.git', '.DS_Store', 'Thumbs.db'}
    if no_default_excludes:
        protected.discard('.DS_Store')
        protected.discard('Thumbs.db')
    result = {n for n in result if not any(part == '.git' for part in PurePosixPath(n).parts)}
    result = {n for n in result if PurePosixPath(n).name not in protected}

    # Apply explicit excludes first (highest priority)
    if excludes:
        result = {n for n in result if not any(match_pattern(n, pat) for pat in excludes)}

    # Apply explicit includes (can re-include even if later default/gitignore would exclude)
    if includes:
        # But explicit include can override default/gitignore, not protected.
        # We'll defer default/gitignore filtering until after inclusion.
        include_matched = {n for n in result if any(match_pattern(n, pat) for pat in includes)}
        result = include_matched

    # Apply gitignore unless disabled, but only if we haven't used explicit includes to re-include?
    # According to precedence: explicit include can restore ignored path, so we apply gitignore
    # only to paths not explicitly included. This is complex. Simpler: apply gitignore first,
    # then allow explicit includes to re-add. We'll implement:
    if not no_gitignore and not explicit and not from_git:
        # Apply gitignore filter to currently selected (after includes may have re-included ignored)
        # We need to know which candidates were ignored before inclusion.
        # Approach: compute initial candidate set, then determine ignored set, then later inclusion can restore.
        # For simplicity, we'll first apply gitignore to the full candidate set (before includes/excludes)
        # and store ignored set. Then after explicit filters, we can re-add explicitly included ignored.
        # But this gets messy. Instead, we'll follow precedence order as spec:
        # protected > explicit exclude > explicit include > gitignore/default > eligibility.
        # That means gitignore applies after explicit include, so explicit include can override gitignore.
        # But then default excludes? They are already protected, so okay.
        # Implementation: first apply explicit filters, then apply gitignore to remaining.
        # That way, explicit include can restore a gitignored path if it was in the original candidate set.
        # However, if we apply gitignore after explicit include, then explicitly included ignored path
        # would be removed again. So we need to apply gitignore before explicit include, then allow
        # explicit include to re-add. That's complicated. Given the spec says explicit include can restore,
        # we'll implement: compute ignored set from the full candidate list, then when applying includes,
        # if a path is explicitly included and was in ignored set, we keep it.
        if not no_gitignore and not explicit and not from_git:
            full_candidates = set(names)
            ignored = full_candidates - apply_gitignore_filter(source, full_candidates)
            # Now, after explicit filters, if a path is in result and was in ignored,
            # we need to check if it was explicitly included. If so, keep; else remove.
            if includes:
                # only keep ignored paths if they match an include pattern
                result = {n for n in result if n not in ignored or any(match_pattern(n, pat) for pat in includes)}
            else:
                result -= ignored

    # Apply default excludes if not disabled (these are not protected, but apply after includes)
    if not no_default_excludes:
        # default excludes are already protected, but we'll re-apply just in case
        for pat in DEFAULT_EXCLUDES:
            result = {n for n in result if not match_pattern(n, pat)}

    # Apply extension filters
    if include_extensions or exclude_extensions:
        result = {n for n in result if extension_selected(n, include_extensions, exclude_extensions)}

    return sorted(result)


# ------------------------- Carrier generation -------------------------

def classify_file(data: bytes) -> str:
    """Return 'text' if valid UTF-8, else 'binary'."""
    if data.startswith(b'\xef\xbb\xbf'):
        return 'binary'  # BOM is not permitted for text
    binary = b'\0' in data
    if binary:
        return 'binary'
    try:
        data.decode('utf-8')
        return 'text'
    except UnicodeDecodeError:
        return 'binary'


def encode_entry(h: TextIO, path: str, data: bytes, readonly: bool) -> bool:
    attrs = [f'path="{safe_path(path)}"']
    if readonly:
        attrs.append('readonly="true"')
    if data.startswith(b'\xef\xbb\xbf'):
        raise UsageError(f'UTF-8 BOM is not permitted: {path}')

    file_type = classify_file(data)
    if file_type == 'binary':
        attrs.append('encoding="base64"')
        h.write('%%FILE ' + ' '.join(attrs) + '\n    ' + base64.b64encode(data).decode('ascii') + '\n%%ENDBLOCK\n')
        return True
    else:
        # text
        attrs.append('escaped="true"')
        h.write('%%FILE ' + ' '.join(attrs) + '\n')
        text = normalize_text(data.decode('utf-8'))
        if text:
            for line in text.split('\n'):
                h.write(encode_text_line(line) + '\n')
        h.write('%%ENDBLOCK\n')
        return True


def write_atomic(output: Path, force: bool, writer) -> None:
    if output == Path('-'):
        # write to stdout
        writer(sys.stdout)
        return
    try:
        atomic_write_text(output, writer, replace=force)
    except FilesystemError as exc:
        message = str(exc)
        if message.startswith("output already exists:"):
            raise WriteConflictError(f"output already exists; use --force to replace it: {output}") from exc
        if message.startswith("refusing unsafe symlink target:"):
            raise WriteConflictError(f"refusing to replace symlink: {output}") from exc
        raise IOErrorDx(message) from exc


# ------------------------- Command handlers -------------------------

def device_output_dir() -> Path:
    override = os.environ.get("DX_DEVICE_DIR")
    return Path(override).expanduser() if override else DEFAULT_DEVICE_DIR


def resolve_default_output(device: bool, source: Path) -> Path:
    """Return default output path without considering --force."""
    if device:
        directory = device_output_dir()
        directory.mkdir(parents=True, exist_ok=True)  # create only if termux dir exists
        highest = 0
        for p in directory.iterdir():
            m = NUMBERED_RE.fullmatch(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
        return directory / f'dx-carrier-{highest+1}.dx.txt'
    else:
        # current directory
        highest = 0
        for p in Path.cwd().iterdir():
            m = NUMBERED_RE.fullmatch(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
        return Path.cwd() / f'dx-carrier-{highest+1}.dx.txt'


def pack_command(a) -> int:
    # Validate flags
    if a.binary and a.skip_binary:
        raise UsageError('--binary and --skip-binary are mutually exclusive')
    if a.quiet and a.verbose:
        raise UsageError('--quiet and --verbose are mutually exclusive')

    source_arg = a.source or (a.root if a.root else '.')
    source = Path(source_arg).resolve()
    root = Path(a.root).resolve() if a.root else source

    if not source.exists():
        raise IOErrorDx(f"source does not exist: {source_arg}")

    # Determine output
    if a.output_opt:
        output = Path(a.output_opt)
        if str(output) == '-':
            output = Path('-')  # special stdout marker
        elif not output.is_absolute():
            output = Path.cwd() / output
        device = False
    else:
        # default behavior
        termux_downloads = Path('~/storage/downloads').expanduser()
        if termux_downloads.exists() and not a.root and not a.path and not a.from_git:
            output = resolve_default_output(device=True, source=source)
            device = True
        else:
            output = resolve_default_output(device=False, source=source)
            device = False
            if not a.quiet:
                print("Notice: Termux download folder not found; writing to the current directory.", file=sys.stderr)

    # Collect paths
    names = collect_paths(
        root=root,
        source=source,
        explicit=a.path,
        from_git=a.from_git,
        includes=a.include,
        excludes=a.exclude,
        include_extensions=a.include_extension,
        exclude_extensions=a.exclude_extension,
        output=output,
        device=device,
        no_gitignore=a.no_gitignore,
        no_default_excludes=a.no_default_excludes,
    )
    if not names:
        raise IOErrorDx('no files selected after applying ignore and filter rules')

    # Classify files once
    file_info = []  # list of (name, data, classification)
    for name in names:
        target = (root / name) if (a.path or a.from_git or a.root) else (source / name)
        if target.is_symlink() or not target.is_file():
            raise IOErrorDx(f"selected path is not a regular file: {name}")
        data = target.read_bytes()
        classification = classify_file(data)
        file_info.append((name, data, classification))

    # Binary policy
    include_binary = a.binary or not a.skip_binary  # default include
    if not include_binary:
        # filter out binary files
        file_info = [(n, d, c) for n, d, c in file_info if c == 'text']
        omitted = sum(1 for _, _, c in file_info if c == 'binary')
        if omitted and not a.quiet:
            for _, _, c in file_info:
                if c == 'binary':
                    print(f"Omitted non-UTF-8: {_}", file=sys.stderr)
    else:
        omitted = 0

    if not file_info:
        raise IOErrorDx('no representable files selected')

    count = len(file_info)
    text_count = sum(1 for _, _, c in file_info if c == 'text')
    binary_count = count - text_count

    # Dry-run output
    if a.dry_run:
        if a.json:
            result = {
                "schema_version": 1,
                "command": "pack",
                "dry_run": True,
                "source": str(source),
                "root": str(root),
                "output": str(output) if output != Path('-') else '-',
                "selected_files": count,
                "text_files": text_count,
                "binary_files": binary_count,
                "skipped_files": omitted,
                "files": [{"path": n, "type": c} for n, _, c in file_info],
            }
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write('\n')
        elif not a.quiet:
            plan = f"DX carrier plan\n"
            plan += f"Source: {source}\n"
            plan += f"Root: {root}\n"
            plan += f"Output: {output if output != Path('-') else 'stdout'}\n\n"
            plan += f"Selected files: {count}\n"
            plan += f"UTF-8 text files: {text_count}\n"
            plan += f"Binary files encoded as base64: {binary_count}\n"
            plan += f"Git-ignored files excluded: (not computed)\n"
            plan += f"Default-excluded files: (not computed)\n"
            plan += f"Explicitly excluded files: (not computed)\n"
            plan += f"Unreadable files: 0\n"
            plan += f"Estimated input size: {sum(len(d) for _, d, _ in file_info) // 1024} KiB\n\n"
            plan += "Files to include:\n"
            for name, _, c in file_info:
                plan += f"  {name}"
                if c == 'binary':
                    plan += " (base64)"
                plan += "\n"
            plan += "\nNo files were written."
            print(plan, file=sys.stderr)
        return 0

    # Actual writing
    def writer(h):
        h.write(f'%%DX {VERSION}\n')
        for name, data, _ in file_info:
            encode_entry(h, name, data, a.readonly)
        h.write('%%END\n')

    if output == Path('-'):
        if a.quiet:
            # quiet mode: nothing extra to stderr, only carrier on stdout
            pass
        else:
            print("Writing carrier to stdout", file=sys.stderr)
        write_atomic(output, a.force, writer)
    else:
        existed = output.exists()
        write_atomic(output, a.force, writer)
        if a.quiet:
            # print only output path to stdout
            print(output)
        else:
            print(f"DX carrier {'replaced' if existed else 'created'}: {output}", file=sys.stderr)
            print(f"Included: {count} files", file=sys.stderr)
            print(f"Skipped non-UTF-8: {omitted} files", file=sys.stderr)
            print(f"Next: dx.py inspect \"{output}\"", file=sys.stderr)
    return 0


def apply_unpack_common(a, is_apply: bool) -> int:
    # read carrier
    _, entries, _ = read_entries(a.carrier)
    root = Path(a.destination).resolve()

    # Determine conflict policy
    if a.force and a.existing != 'overwrite':
        # --force implies overwrite
        if a.existing != 'skip':  # default is 'skip', so force overrides
            policy = 'overwrite'
        else:
            # if user explicitly set --existing skip and also --force, that's contradictory
            # But we can allow --force to override? We'll treat as error if both set and different.
            # For simplicity, --force always means overwrite.
            policy = 'overwrite'
    else:
        policy = a.existing or 'skip'

    if a.dry_run:
        # no filesystem modifications
        would_write = 0
        would_skip_existing = 0
        would_skip_readonly = 0
        for e in entries:
            if e.readonly:
                would_skip_readonly += 1
                continue
            target = (root / Path(*PurePosixPath(e.path).parts)).resolve()
            if target != root and root not in target.parents:
                raise UsageError(f"path escapes destination: {e.path}")
            if target.exists() and policy == 'skip':
                would_skip_existing += 1
                continue
            if target.exists() and policy == 'fail':
                would_skip_existing += 1
                continue
            would_write += 1

        if a.json:
            json.dump({
                "schema_version": 1,
                "command": "apply" if is_apply else "unpack",
                "dry_run": True,
                "destination": str(root),
                "files_would_write": would_write,
                "files_skipped_existing": would_skip_existing,
                "files_skipped_readonly": would_skip_readonly,
            }, sys.stdout, indent=2)
            sys.stdout.write('\n')
        elif not a.quiet:
            print(f"Would write {would_write} files to {root}", file=sys.stderr)
            if would_skip_existing:
                print(f"Would skip {would_skip_existing} existing files", file=sys.stderr)
            if would_skip_readonly:
                print(f"Would skip {would_skip_readonly} read-only entries", file=sys.stderr)
        return 0

    # actual writing
    written = 0
    skipped_existing = 0
    skipped_readonly = 0

    # We must not create destination directory until we know we will write.
    # But root.mkdir may be needed only if there are files to write.
    # We'll create after confirmation that at least one file will be written.
    files_to_write = []
    for e in entries:
        if e.readonly:
            skipped_readonly += 1
            continue
        target = (root / Path(*PurePosixPath(e.path).parts)).resolve()
        if target != root and root not in target.parents:
            raise UsageError(f"path escapes destination: {e.path}")
        if target.exists():
            if policy == 'skip':
                skipped_existing += 1
                if not a.quiet:
                    print(f"Skipped existing: {e.path}", file=sys.stderr)
                continue
            elif policy == 'fail':
                raise WriteConflictError(f"file exists: {target}")
            # else overwrite
        files_to_write.append((e, target))

    if not files_to_write:
        if not a.quiet:
            print("No files to write.", file=sys.stderr)
        return 0

    # Now create root directory if needed
    root.mkdir(parents=True, exist_ok=True)

    for e, target in files_to_write:
        target.parent.mkdir(parents=True, exist_ok=True)
        # atomic write
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=target.name + '.tmp.', dir=target.parent)
            with os.fdopen(fd, 'wb') as f:
                f.write(e.data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except:
                pass
            raise IOErrorDx(f"failed to write {target}: {exc}") from exc
        written += 1
        if a.verbose:
            print(f"  wrote {e.path}", file=sys.stderr)

    if not a.quiet:
        summary = f"Applied {written} files to {root}"
        if skipped_existing:
            summary += f"\nSkipped {skipped_existing} existing files"
        if skipped_readonly:
            summary += f"\nSkipped {skipped_readonly} read-only entries"
        print(summary, file=sys.stderr)

    return 0


def unpack_command(a):
    return apply_unpack_common(a, is_apply=False)


def apply_command(a):
    return apply_unpack_common(a, is_apply=True)


def inspect_command(a) -> int:
    # validate conflicting output modes
    primary_modes = [a.list, a.hashes, a.readonly, a.cat is not None, a.compare is not None, a.verify, a.summary]
    if sum(1 for m in primary_modes if m) > 1:
        raise UsageError("primary output modes are mutually exclusive; choose one of --list, --hashes, --readonly, --cat, --compare, --verify, --summary")

    version, entries, notes = read_entries(a.carrier)

    if a.json:
        # JSON mode: can be combined with list/compare/etc but not cat.
        if a.cat is not None:
            raise UsageError("--cat cannot be combined with --json")
        data = {
            "schema_version": 1,
            "command": "inspect",
            "version": version,
            "files": len(entries),
            "note_blocks": notes,
            "entries": [
                {
                    "path": e.path,
                    "readonly": e.readonly,
                    "encoding": e.encoding or "text",
                    "escaped": e.escaped,
                    "sha256": hashlib.sha256(e.data).hexdigest(),
                    "size": len(e.data),
                }
                for e in entries
            ],
        }
        if a.list:
            data["mode"] = "list"
            data["paths"] = [e.path for e in entries]
        elif a.hashes:
            data["mode"] = "hashes"
            data["hashes"] = [{"path": e.path, "sha256": hashlib.sha256(e.data).hexdigest()} for e in entries]
        elif a.readonly:
            data["mode"] = "readonly"
            data["readonly_paths"] = [e.path for e in entries if e.readonly]
        elif a.compare is not None:
            # compute differences
            root = Path(a.compare).resolve()
            diffs = []
            for e in entries:
                p = root / Path(*PurePosixPath(e.path).parts)
                if not p.is_file() or p.read_bytes() != e.data:
                    diffs.append({"path": e.path, "status": "M" if p.is_file() else "A"})
            data["mode"] = "compare"
            data["differences"] = diffs
        elif a.verify:
            # structural verification already done during parse; report success
            data["mode"] = "verify"
            data["valid"] = True
            data["errors"] = []
        else:
            data["mode"] = "summary"
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write('\n')
        return 0

    if a.list:
        for e in entries:
            print(e.path)
        return 0
    if a.hashes:
        for e in entries:
            print(f"{hashlib.sha256(e.data).hexdigest()}  {e.path}")
        return 0
    if a.readonly:
        for e in entries:
            if e.readonly:
                print(e.path)
        return 0
    if a.cat is not None:
        matches = [e for e in entries if e.path == a.cat]
        if len(matches) != 1:
            raise InvalidCarrierError(f"expected exactly one file named {a.cat!r}, found {len(matches)}")
        sys.stdout.buffer.write(matches[0].data)
        return 0
    if a.compare is not None:
        root = Path(a.compare).resolve()
        differences = []
        for e in entries:
            p = root / Path(*PurePosixPath(e.path).parts)
            if not p.is_file():
                differences.append(("A", e.path))
            elif p.read_bytes() != e.data:
                differences.append(("M", e.path))
            elif e.readonly and p.stat().st_mode & 0o444 == 0:
                differences.append(("R", e.path))
        for status, path in differences:
            print(f"{status} {path}")
        if not a.quiet:
            print(f"{len(differences)} files differ out of {len(entries)} carrier entries checked.", file=sys.stderr)
        return 1 if differences else 0
    if a.verify:
        # Structural verification already done during parse. No content hash to check.
        if not a.quiet:
            print(f"Carrier OK\n{len(entries)} files verified", file=sys.stderr)
        return 0
    # default summary
    text_count = sum(1 for e in entries if e.encoding is None)
    binary_count = len(entries) - text_count
    readonly_count = sum(1 for e in entries if e.readonly)
    total_size = sum(len(e.data) for e in entries)

    if not a.quiet:
        print(f"DX version: {version}")
        print(f"Files: {len(entries)}")
        print(f"Text files: {text_count}")
        print(f"Binary files: {binary_count}")
        print(f"Read-only entries: {readonly_count}")
        print(f"NOTE blocks: {notes}")
        print(f"Total decoded size: {total_size} bytes")
    return 0


# ------------------------- Argument parsing -------------------------

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    top = Parser(prog='dx.py', add_help=False)
    top.add_argument('-h', '--help', action='store_true', help='Show this help message and exit')
    top.add_argument('-V', '--version', action='store_true', help='Show version and exit')
    # Global quiet/verbose are added to each subparser as well via parent.
    parent = Parser(add_help=False)
    parent.add_argument('-q', '--quiet', action='store_true', help='Suppress non-error diagnostics')
    parent.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    sub = top.add_subparsers(dest='command')

    # pack
    p = sub.add_parser('pack', aliases=['p'], parents=[parent], help='Pack files into a DX carrier',
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description='Pack files. With no arguments, defaults to --dry-run of current directory.')
    p.add_argument('source', nargs='?', metavar='SOURCE', help='Directory or file to pack (default: current directory)')
    p.add_argument('output', nargs='?', metavar='OUTPUT', help=argparse.SUPPRESS)  # deprecated
    p.add_argument('-o', '--output', dest='output_opt', help='Output carrier path, or "-" for stdout')
    p.add_argument('-r', '--root', help='Advanced: path mapping root')
    p.add_argument('-p', '--path', action='append', default=[], help='Advanced: exact file or folder to pack (repeatable)')
    p.add_argument('-g', '--from-git', action='store_true', help='Advanced: pack Git changes')
    p.add_argument('-i', '--include', action='append', default=[], help='Include only paths matching PATTERN (repeatable)')
    p.add_argument('-I', '--exclude', action='append', default=[], help='Exclude paths matching PATTERN (repeatable)')
    p.add_argument('-x', '--include-extension', action='append', default=[], metavar='EXT', help='Include only files with extension')
    p.add_argument('-X', '--exclude-extension', action='append', default=[], metavar='EXT', help='Exclude files with extension')
    p.add_argument('-b', '--binary', action='store_true', help='Explicitly include non-UTF-8 files (default)')
    p.add_argument('-B', '--skip-binary', action='store_true', help='Skip non-UTF-8 files')
    p.add_argument('--readonly', action='store_true', help='Mark all entries as read-only')
    p.add_argument('-G', '--no-gitignore', action='store_true', help='Do not apply Git ignore rules')
    p.add_argument('--no-default-excludes', action='store_true', help='Do not apply default excludes')
    p.add_argument('-n', '--dry-run', action='store_true', help='Show plan without writing')
    p.add_argument('-f', '--force', action='store_true', help='Overwrite existing output')
    p.add_argument('-j', '--json', action='store_true', help='Output plan as JSON (with --dry-run)')
    p.set_defaults(func=pack_command)

    # unpack / apply
    for name, aliases in [('unpack', ['u']), ('apply', ['a'])]:
        q = sub.add_parser(name, aliases=aliases, parents=[parent], help='Extract carrier files to a destination')
        q.add_argument('carrier', metavar='CARRIER', help='Carrier file or "-" for stdin')
        q.add_argument('destination', nargs='?', default='.', metavar='DESTINATION', help='Destination directory (default: .)')
        q.add_argument('-f', '--force', action='store_true', help='Overwrite existing files (same as --existing overwrite)')
        q.add_argument('--existing', choices=['fail', 'skip', 'overwrite'], default='skip', help='Conflict policy')
        q.add_argument('-n', '--dry-run', action='store_true', help='Show what would be done without writing')
        q.add_argument('-j', '--json', action='store_true', help='Output dry-run plan as JSON')
        q.set_defaults(func=unpack_command if name == 'unpack' else apply_command)

    # inspect
    insp = sub.add_parser('inspect', parents=[parent], help='Inspect a DX carrier')
    insp.add_argument('carrier', metavar='CARRIER', help='Carrier file or "-" for stdin')
    insp.add_argument('-l', '--list', action='store_true', help='List file paths')
    insp.add_argument('-H', '--hashes', action='store_true', help='Show SHA-256 hashes')
    insp.add_argument('-R', '--readonly', action='store_true', help='List read-only paths')
    insp.add_argument('-c', '--cat', metavar='PATH', help='Write file content to stdout')
    insp.add_argument('-C', '--compare', metavar='DIR', help='Compare carrier with directory')
    insp.add_argument('--check-extra', action='store_true', help='Also report extra local files (with --compare)')
    insp.add_argument('--summary', action='store_true', help='Show summary (default)')
    insp.add_argument('--verify', action='store_true', help='Verify carrier structure')
    insp.add_argument('-j', '--json', action='store_true', help='Output JSON')
    insp.set_defaults(func=inspect_command)

    return top


# ------------------------- Main -------------------------

TOP_HELP = '''DX v2.0.0 carrier utility

Usage:
  dx.py COMMAND [arguments]

Commands:
  pack       Pack files into a DX carrier
  unpack     Extract files from a carrier
  apply      Alias for unpack
  inspect    Inspect a carrier

Quick start:
  dx.py pack
  dx.py pack . -o project.dx.txt
  dx.py pack . --dry-run
  dx.py unpack project.dx.txt .
  dx.py inspect project.dx.txt --list

Run "dx.py COMMAND -h" for command-specific help.
'''

def main(argv=None):
    argsv = list(sys.argv[1:] if argv is None else argv)
    if not argsv:
        argsv = ['pack', '--dry-run']
    if argsv in (['-h'], ['--help']):
        print(TOP_HELP, end='')
        return 0
    if argsv in (['-V'], ['--version']):
        print(f"dx.py {VERSION}")
        return 0

    # Determine command for error usage
    command = argsv[0] if argsv and argsv[0] in ('pack', 'p', 'unpack', 'u', 'apply', 'a', 'inspect') else None
    canonical = {'p': 'pack', 'u': 'unpack', 'a': 'apply'}.get(command, command)

    parser = build_parser()
    try:
        a = parser.parse_args(argsv)
        if a.help:
            if command:
                # print subcommand help without private API
                # we can use parser._subparsers, but better: just print TOP_HELP?
                # For simplicity, we'll rely on argparse's default behavior after setting add_help=False?
                # We can manually print help for subparser by parsing help request.
                # Not ideal. We'll just print TOP_HELP for now, but that loses detail.
                # We could call print_help on the specific subparser using a lookup.
                # We'll implement a simple mapping.
                sub_parsers_action = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
                if command in sub_parsers_action.choices:
                    sub_parsers_action.choices[command].print_help()
                else:
                    print(TOP_HELP, end='')
                return 0
            else:
                print(TOP_HELP, end='')
                return 0
        if not hasattr(a, 'func'):
            print(TOP_HELP, end='')
            return 0

        # Resolve output option conflict (pack)
        if a.command in ('pack', 'p'):
            if a.output and a.output_opt:
                raise UsageError("output was specified both positionally and with --output. Use only --output.")
            if a.output:
                if not a.quiet:
                    print("WARNING: positional OUTPUT is deprecated. Use -o OUTPUT.", file=sys.stderr)
                a.output_opt = a.output
            a.output = a.output_opt

        return a.func(a)
    except DxError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if canonical:
            print(f"Usage: dx.py {canonical} [OPTIONS]", file=sys.stderr)
            print(f'Run "dx.py {canonical} -h" for complete help.', file=sys.stderr)
        return e.exit_code
    except (OSError, UnicodeError, subprocess.CalledProcessError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4  # IO error

if __name__ == '__main__':
    raise SystemExit(main())