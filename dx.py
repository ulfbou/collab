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
    trailing_newlines: int = 0


def safe_user_path(raw: str) -> str:
    """Validate a user-supplied path; raises UsageError."""
    try:
        return require_safe_relative_path(raw)
    except ValidationError as exc:
        raise UsageError(f"unsafe path: {raw!r}") from exc


def safe_carrier_path(raw: str) -> str:
    """Validate a path from a carrier; raises InvalidCarrierError."""
    try:
        return require_safe_relative_path(raw)
    except ValidationError as exc:
        raise InvalidCarrierError(f"unsafe carrier path: {raw!r}") from exc


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


def decoded_payload(path: str, body: list[str], encoding: str | None, escaped: bool, trailing_newlines: int = 0) -> bytes:
    if encoding in (None, ''):
        text = '\n'.join(decode_text_line(x, escaped) for x in body)
        # Preserve exact trailing newlines as recorded
        return (text.rstrip('\n') + '\n' * trailing_newlines).encode('utf-8')
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
            # Strict: only trailing newline allowed after %%END
            if i + 1 < len(lines) and any(line.strip() for line in lines[i+1:]):
                raise InvalidCarrierError("content after %%END is not allowed")
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
            attrs = {}
            for key, val in ATTR_RE.findall(line):
                if key in attrs:
                    raise InvalidCarrierError(f"duplicate attribute {key!r} on FILE {line}")
                attrs[key] = val
            if 'path' not in attrs:
                raise InvalidCarrierError(f"FILE without path at line {i+1}")
            path = safe_carrier_path(attrs['path'])
            if path in seen:
                raise InvalidCarrierError(f"duplicate path: {path}")
            seen.add(path)
            # Validate attributes
            allowed = {'path', 'readonly', 'encoding', 'escaped', 'trailing_newlines'}
            for key in attrs:
                if key not in allowed:
                    raise InvalidCarrierError(f"unsupported attribute {key!r} on FILE {path}")
            if 'readonly' in attrs and attrs['readonly'] not in ('true', 'false'):
                raise InvalidCarrierError(f"readonly must be 'true' or 'false', got {attrs['readonly']!r}")
            if 'escaped' in attrs and attrs['escaped'] not in ('true', 'false'):
                raise InvalidCarrierError(f"escaped must be 'true' or 'false', got {attrs['escaped']!r}")
            encoding = attrs.get('encoding', '')
            if encoding not in ('', 'base64'):
                raise InvalidCarrierError(f"unsupported encoding {encoding!r}")
            if encoding == 'base64' and attrs.get('escaped', 'false') == 'true':
                raise InvalidCarrierError("escaped='true' is only valid for text entries")
            if 'trailing_newlines' in attrs and encoding == 'base64':
                raise InvalidCarrierError("trailing_newlines is only valid for text entries")
            trailing = int(attrs.get('trailing_newlines', '0'))
            if trailing < 0:
                raise InvalidCarrierError("trailing_newlines must be non-negative")
            i += 1
            body = []
            while i < len(lines) and lines[i] != '%%ENDBLOCK':
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise InvalidCarrierError(f"unterminated file block: {path}")
            escaped = attrs.get('escaped', 'false') == 'true'
            if version != 'v2.0.0':
                # legacy: always assume escaped behavior (indentation-based)
                escaped = True
            entries.append(Entry(
                path,
                decoded_payload(path, body, encoding, escaped, trailing),
                attrs.get('readonly', 'false') == 'true',
                encoding if encoding else None,
                escaped,
                trailing
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


def normalize_extension(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        raise UsageError('extension must not be empty')
    if '/' in value or '\\' in value or any(ch in value for ch in ('\0', '\n', '\r')):
        raise UsageError(f"invalid extension: {raw!r}")
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

    for ext in exclude_set:
        if matches_compound_extension(basename, ext):
            return False

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
        out.append(safe_user_path(path))
    return sorted(set(out))


def git_repo_root(path: Path) -> Optional[Path]:
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path.parent if path.is_file() else path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        if probe.returncode != 0:
            cwd = path.parent if path.is_file() else path
            if any((candidate / '.git' / 'HEAD').is_file() for candidate in (cwd, *cwd.parents)):
                message = probe.stderr.strip() or 'git rev-parse failed'
                raise IOErrorDx(message)
            return None
        return Path(probe.stdout.strip()).resolve()
    except FileNotFoundError as exc:
        cwd = path.parent if path.is_file() else path
        if any((candidate / '.git' / 'HEAD').is_file() for candidate in (cwd, *cwd.parents)):
            raise IOErrorDx('git executable is unavailable inside a Git repository') from exc
        return None


def git_allowed_paths(root: Path) -> Optional[set[str]]:
    """Get set of relative paths that are tracked or untracked but not ignored.
    Returns None if not a Git repository."""
    try:
        p = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if p.returncode != 0:
            # If git command failed, raise
            stderr = p.stderr.decode('utf-8', 'replace').strip()
            raise IOErrorDx(f"git ls-files failed: {stderr}")
        paths = set()
        for line in p.stdout.split(b'\n'):
            if line:
                try:
                    rel = line.decode('utf-8', 'strict').replace('\\', '/')
                except UnicodeDecodeError as exc:
                    raise IOErrorDx(f"git returned undecodable path: {line!r}") from exc
                paths.add(rel)
        return paths
    except FileNotFoundError:
        return None


def apply_gitignore_filter(source: Path, candidates: set[str]) -> set[str]:
    """Return subset of candidates that are not git-ignored untracked files."""
    if not candidates:
        return candidates
    repo_root = git_repo_root(source)
    if repo_root is None:
        return candidates  # not inside a repo, no filtering
    allowed = git_allowed_paths(repo_root)  # may raise on error
    if allowed is None:
        return candidates  # git unavailable? Should not happen
    filtered = set()
    for name in candidates:
        abs_path = (source / Path(*PurePosixPath(name).parts)).resolve()
        try:
            rel_to_repo = abs_path.relative_to(repo_root).as_posix()
        except ValueError:
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
                  no_gitignore: bool = False, no_default_excludes: bool = False) -> tuple[list[str], dict[str, int]]:
    """Collect selected paths and return (sorted_paths, stats_counts)."""
    if explicit and from_git:
        raise UsageError('--path and --from-git are mutually exclusive')

    # Build initial candidate set
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
        if source.is_file():
            names = [source.relative_to(root).as_posix()]
        else:
            names = []
            for directory, child_dirs, files in os.walk(source, topdown=True, followlinks=False):
                current = Path(directory)
                child_dirs[:] = sorted(name for name in child_dirs if name != '.git' and not (current / name).is_symlink())
                for name in sorted(files):
                    candidate = current / name
                    if candidate.is_file() and not candidate.is_symlink():
                        names.append(candidate.relative_to(source).as_posix())

    all_candidates = set(names)

    # Self-exclusion
    output_resolved = output.resolve() if output and output != Path('-') else None
    if output_resolved:
        all_candidates = {n for n in all_candidates if (root / n).resolve() != output_resolved}

    # Protected exclusions (always applied)
    protected = {'.git'}
    if not no_default_excludes:
        protected.update({'.DS_Store', 'Thumbs.db'})
    protected_candidates = {n for n in all_candidates if any(part == '.git' for part in PurePosixPath(n).parts) or PurePosixPath(n).name in protected}
    candidates_after_protected = all_candidates - protected_candidates

    # Explicit excludes (highest priority)
    explicitly_excluded = {n for n in candidates_after_protected if any(match_pattern(n, pat) for pat in excludes)}
    candidates_after_explicit_exclude = candidates_after_protected - explicitly_excluded

    # Explicit includes (may re-add ignored files)
    if includes:
        explicitly_included = {n for n in candidates_after_explicit_exclude if any(match_pattern(n, pat) for pat in includes)}
        candidates_after_explicit_include = explicitly_included
    else:
        candidates_after_explicit_include = candidates_after_explicit_exclude

    # Apply gitignore (but explicit include can override)
    git_ignored = set()
    if not no_gitignore and not explicit and not from_git and not source.is_file():
        # Determine which candidates are ignored before explicit include
        full_after_protected_explicit = candidates_after_protected - explicitly_excluded
        allowed = apply_gitignore_filter(source, full_after_protected_explicit)
        git_ignored = full_after_protected_explicit - allowed
        # Remove git-ignored unless they were explicitly included
        candidates_after_gitignore = {n for n in candidates_after_explicit_include if n not in git_ignored or (includes and any(match_pattern(n, pat) for pat in includes))}
    else:
        candidates_after_gitignore = candidates_after_explicit_include

    # Apply default excludes (already protected, but double-check)
    if not no_default_excludes:
        candidates_after_gitignore = {n for n in candidates_after_gitignore if not any(match_pattern(n, pat) for pat in DEFAULT_EXCLUDES)}

    # Apply extension filters
    if include_extensions or exclude_extensions:
        candidates_final = {n for n in candidates_after_gitignore if extension_selected(n, include_extensions, exclude_extensions)}
    else:
        candidates_final = candidates_after_gitignore

    # Compute stats
    stats = {
        'protected_excluded': len(protected_candidates),
        'explicit_excluded': len(explicitly_excluded),
        'git_ignored': len(git_ignored),
        'default_excluded': len(protected_candidates) if not no_default_excludes else 0,  # approximate, we'll adjust below
        'extension_excluded': len(candidates_after_gitignore) - len(candidates_final),
        'selected': len(candidates_final),
    }
    # Correct default_excluded: those that were not git-ignored and not explicit excluded but were in protected
    if not no_default_excludes:
        stats['default_excluded'] = len(protected_candidates - set(['.git'])) if False else 0
        # simpler: we treat protected as both .git and default; we can compute separately:
        # For reporting, we can count .DS_Store etc separately but not necessary now.
        stats['protected_excluded'] = len(protected_candidates)
        stats['default_excluded'] = 0  # we'll not separate .git from others; user sees "protected"

    return sorted(candidates_final), stats


# ------------------------- Carrier generation -------------------------

def classify_file(data: bytes) -> str:
    """Return 'text' if valid UTF-8 with only LF line endings and no BOM, else 'binary'."""
    if data.startswith(b'\xef\xbb\xbf'):
        return 'binary'  # BOM not allowed in text mode
    if b'\r' in data:
        return 'binary'  # preserve CRLF/CR exactly via base64
    if b'\0' in data:
        return 'binary'
    try:
        data.decode('utf-8')
        return 'text'
    except UnicodeDecodeError:
        return 'binary'


def encode_entry(h: TextIO, path: str, data: bytes, readonly: bool) -> bool:
    attrs = [f'path="{safe_user_path(path)}"']
    if readonly:
        attrs.append('readonly="true"')

    file_type = classify_file(data)
    if file_type == 'binary':
        attrs.append('encoding="base64"')
        h.write('%%FILE ' + ' '.join(attrs) + '\n    ' + base64.b64encode(data).decode('ascii') + '\n%%ENDBLOCK\n')
        return True
    else:
        # text
        text = data.decode('utf-8')
        # Count trailing newlines
        trailing = len(text) - len(text.rstrip('\n'))
        text_stripped = text.rstrip('\n')
        attrs.append('escaped="true"')
        if trailing:
            attrs.append(f'trailing_newlines="{trailing}"')
        h.write('%%FILE ' + ' '.join(attrs) + '\n')
        if text_stripped:
            for line in text_stripped.split('\n'):
                h.write(encode_text_line(line) + '\n')
        h.write('%%ENDBLOCK\n')
        return True


def write_atomic(output: Path, force: bool, writer) -> None:
    if output == Path('-'):
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
    """Return default output path without filesystem mutation."""
    if device:
        directory = device_output_dir()
        highest = 0
        if directory.is_dir():
            for p in directory.iterdir():
                m = NUMBERED_RE.fullmatch(p.name)
                if m:
                    highest = max(highest, int(m.group(1)))
        return directory / f'dx-carrier-{highest+1}.dx.txt'
    else:
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
    if not source.exists():
        raise IOErrorDx(f"source does not exist: {source_arg}")

    # Determine root and source relationship
    if a.root:
        root = Path(a.root).resolve()
    else:
        if source.is_file():
            root = source.parent
        else:
            root = source

    # Determine output
    if a.output_opt:
        output = Path(a.output_opt)
        if str(output) == '-':
            output = Path('-')
        elif not output.is_absolute():
            output = Path.cwd() / output
        device = False
    else:
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
    names, stats = collect_paths(
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
    file_info = []
    for name in names:
        target = (root / name) if (a.path or a.from_git or a.root or source.is_file()) else (source / name)
        if target.is_symlink() or not target.is_file():
            raise IOErrorDx(f"selected path is not a regular file: {name}")
        data = target.read_bytes()
        classification = classify_file(data)
        file_info.append((name, data, classification))

    # Binary policy
    include_binary = a.binary or not a.skip_binary
    omitted_info = []
    if not include_binary:
        omitted_info = [(n, d, c) for n, d, c in file_info if c == 'binary']
        file_info = [(n, d, c) for n, d, c in file_info if c == 'text']
        omitted = len(omitted_info)
        if omitted and not a.quiet:
            for name, _, _ in omitted_info:
                print(f"Omitted non-UTF-8: {name}", file=sys.stderr)
    else:
        omitted = 0

    if not file_info:
        raise IOErrorDx('no representable files selected')

    count = len(file_info)
    text_count = sum(1 for _, _, c in file_info if c == 'text')
    binary_count = count - text_count

    # Dry-run
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
                "filter_counts": stats,
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
            plan += f"Git-ignored files excluded: {stats['git_ignored']}\n"
            plan += f"Default-excluded files: {stats['protected_excluded']}\n"
            plan += f"Explicitly excluded files: {stats['explicit_excluded']}\n"
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
        if not a.quiet:
            print("Writing carrier to stdout", file=sys.stderr)
        write_atomic(output, a.force, writer)
    else:
        # Ensure parent directory exists (only for actual write)
        output.parent.mkdir(parents=True, exist_ok=True)
        existed = output.exists()
        write_atomic(output, a.force, writer)
        if a.quiet:
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
        if a.existing is not None and a.existing != 'overwrite':
            raise UsageError("--force and --existing are contradictory; use --force with --existing overwrite, or only one.")
        policy = 'overwrite'
    elif a.force and a.existing == 'overwrite':
        policy = 'overwrite'
    elif a.existing is not None:
        policy = a.existing
    else:
        policy = 'skip'  # default

    # Dry-run validation identical to real operation, but no writes
    if a.dry_run:
        would_write = 0
        would_skip_existing = 0
        would_skip_readonly = 0
        for e in entries:
            if e.readonly:
                would_skip_readonly += 1
                continue
            lexical_target = root / Path(*PurePosixPath(e.path).parts)
            if lexical_target.is_symlink():
                raise WriteConflictError(f"destination is a symlink: {lexical_target}")
            target = lexical_target.resolve()
            if target != root and root not in target.parents:
                raise UsageError(f"path escapes destination: {e.path}")
            if target.exists() or target.is_symlink():
                if policy == 'skip':
                    would_skip_existing += 1
                    continue
                elif policy == 'fail':
                    raise WriteConflictError(f"file exists and policy is fail: {target}")
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

    # Actual writing
    written = 0
    skipped_existing = 0
    skipped_readonly = 0
    files_to_write = []

    for e in entries:
        if e.readonly:
            skipped_readonly += 1
            continue
        lexical_target = root / Path(*PurePosixPath(e.path).parts)
        if lexical_target.is_symlink():
            raise WriteConflictError(f"destination is a symlink: {lexical_target}")
        target = lexical_target.resolve()
        if target != root and root not in target.parents:
            raise UsageError(f"path escapes destination: {e.path}")
        if target.is_symlink():
            raise WriteConflictError(f"destination is a symlink: {target}")
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

    # Create root directory only now
    root.mkdir(parents=True, exist_ok=True)

    for e, target in files_to_write:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=target.name + '.tmp.', dir=target.parent)
            with os.fdopen(fd, 'wb') as f:
                f.write(e.data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception as exc:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
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
                    "trailing_newlines": e.trailing_newlines,
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
            root = Path(a.compare).resolve()
            diffs = []
            extras = []
            local_files = set()
            if root.is_dir():
                for p in root.rglob('*'):
                    if p.is_file():
                        rel = p.relative_to(root).as_posix()
                        local_files.add(rel)
            for e in entries:
                p = root / Path(*PurePosixPath(e.path).parts)
                if not p.is_file():
                    diffs.append({"path": e.path, "status": "A"})
                elif p.read_bytes() != e.data:
                    diffs.append({"path": e.path, "status": "M"})
            if a.check_extra:
                carrier_paths = {e.path for e in entries}
                for local in local_files:
                    if local not in carrier_paths:
                        extras.append({"path": local, "status": "D"})
            data["mode"] = "compare"
            data["differences"] = diffs + extras
            data["extra_files"] = extras
            data["exit_code"] = 1 if (diffs or extras) else 0
        elif a.verify:
            data["mode"] = "verify"
            data["valid"] = True
            data["errors"] = []
        else:
            data["mode"] = "summary"
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write('\n')
        # JSON must respect exit codes
        if a.compare is not None:
            return 1 if (diffs or extras) else 0
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
        diffs = []
        extras = []
        carrier_paths = {e.path for e in entries}
        if root.is_dir():
            local_files = set()
            for p in root.rglob('*'):
                if p.is_file():
                    rel = p.relative_to(root).as_posix()
                    local_files.add(rel)
            for e in entries:
                p = root / Path(*PurePosixPath(e.path).parts)
                if not p.is_file():
                    diffs.append(("A", e.path))
                elif p.read_bytes() != e.data:
                    diffs.append(("M", e.path))
            if a.check_extra:
                for local in local_files:
                    if local not in carrier_paths:
                        extras.append(("D", local))
        for status, path in diffs + extras:
            print(f"{status} {path}")
        if not a.quiet:
            print(f"{len(diffs)+len(extras)} files differ out of {len(entries)} carrier entries checked.", file=sys.stderr)
        return 1 if (diffs or extras) else 0
    if a.verify:
        # Structural verification already done during parse.
        if not a.quiet:
            print("Carrier structure OK", file=sys.stderr)
            print(f"{len(entries)} entries parsed successfully", file=sys.stderr)
            print("No content hashes were available for integrity verification.", file=sys.stderr)
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
    # Global quiet/verbose on top-level (so both positions work)
    top.add_argument('-q', '--quiet', action='store_true', help='Suppress non-error diagnostics')
    top.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    sub = top.add_subparsers(dest='command')

    # pack
    p = sub.add_parser('pack', aliases=['p'], help='Pack files into a DX carrier',
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description='Pack files. With no arguments, defaults to --dry-run of current directory.')
    p.add_argument('-q', '--quiet', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('-v', '--verbose', action='store_true', help=argparse.SUPPRESS)
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
        q = sub.add_parser(name, aliases=aliases, help='Extract carrier files to a destination')
        q.add_argument('-q', '--quiet', action='store_true', help=argparse.SUPPRESS)
        q.add_argument('-v', '--verbose', action='store_true', help=argparse.SUPPRESS)
        q.add_argument('carrier', metavar='CARRIER', help='Carrier file or "-" for stdin')
        q.add_argument('destination', nargs='?', default='.', metavar='DESTINATION', help='Destination directory (default: .)')
        q.add_argument('-f', '--force', action='store_true', help='Overwrite existing files (same as --existing overwrite)')
        q.add_argument('--existing', choices=['fail', 'skip', 'overwrite'], default=None, help='Conflict policy')
        q.add_argument('-n', '--dry-run', action='store_true', help='Show what would be done without writing')
        q.add_argument('-j', '--json', action='store_true', help='Output dry-run plan as JSON')
        q.set_defaults(func=unpack_command if name == 'unpack' else apply_command)

    # inspect
    insp = sub.add_parser('inspect', help='Inspect a DX carrier')
    insp.add_argument('-q', '--quiet', action='store_true', help=argparse.SUPPRESS)
    insp.add_argument('-v', '--verbose', action='store_true', help=argparse.SUPPRESS)
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

    global_quiet = any(arg in ("-q", "--quiet") for arg in argsv)
    global_verbose = any(arg in ("-v", "--verbose") for arg in argsv)
    normalized_args = [arg for arg in argsv if arg not in ("-q", "--quiet", "-v", "--verbose")]

    parser = build_parser()
    try:
        a = parser.parse_args(normalized_args)
        a.quiet = global_quiet
        a.verbose = global_verbose

        if not hasattr(a, 'func'):
            print(TOP_HELP, end='')
            return 0

        # Validate global quiet/verbose conflict
        if getattr(a, 'quiet', False) and getattr(a, 'verbose', False):
            raise UsageError('--quiet and --verbose are mutually exclusive')

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
    except InvalidCarrierError as e:
        if hasattr(a, 'command') and a.command == 'inspect' and getattr(a, 'json', False):
            json.dump({
                "schema_version": 1,
                "command": "inspect",
                "mode": "verify",
                "valid": False,
                "errors": [{"code": "invalid_carrier", "message": str(e)}]
            }, sys.stdout, indent=2)
            sys.stdout.write('\n')
            return e.exit_code
        print(f"ERROR: {e}", file=sys.stderr)
        # fall through to usage printing
        command = a.command if hasattr(a, 'command') else None
        usage_map = {
            'pack': 'dx.py pack [SOURCE] [OPTIONS]',
            'p': 'dx.py pack [SOURCE] [OPTIONS]',
            'unpack': 'dx.py unpack CARRIER [DESTINATION] [OPTIONS]',
            'u': 'dx.py unpack CARRIER [DESTINATION] [OPTIONS]',
            'apply': 'dx.py apply CARRIER [DESTINATION] [OPTIONS]',
            'a': 'dx.py apply CARRIER [DESTINATION] [OPTIONS]',
            'inspect': 'dx.py inspect CARRIER [OPTIONS]',
        }
        if command in usage_map:
            print(f"Usage:\n  {usage_map[command]}", file=sys.stderr)
            print(f'Run "dx.py {command} -h" for complete help.', file=sys.stderr)
        return e.exit_code
    except DxError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        command = a.command if hasattr(a, 'command') else None
        usage_map = {
            'pack': 'dx.py pack [SOURCE] [OPTIONS]',
            'p': 'dx.py pack [SOURCE] [OPTIONS]',
            'unpack': 'dx.py unpack CARRIER [DESTINATION] [OPTIONS]',
            'u': 'dx.py unpack CARRIER [DESTINATION] [OPTIONS]',
            'apply': 'dx.py apply CARRIER [DESTINATION] [OPTIONS]',
            'a': 'dx.py apply CARRIER [DESTINATION] [OPTIONS]',
            'inspect': 'dx.py inspect CARRIER [OPTIONS]',
        }
        if command in usage_map:
            print(f"Usage:\n  {usage_map[command]}", file=sys.stderr)
            print(f'Run "dx.py {command} -h" for complete help.', file=sys.stderr)
        return e.exit_code
    except (OSError, UnicodeError, subprocess.CalledProcessError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4

if __name__ == '__main__':
    raise SystemExit(main())
