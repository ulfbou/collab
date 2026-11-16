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
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
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
class EmptySelectionError(DxError):
    exit_code = 7


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
    if not escaped:
        return line
    if not line.startswith('    '):
        raise InvalidCarrierError(f"escaped text payload line is not indented: {line!r}")
    line = line[4:]
    return line[4:] if line.startswith('    %%') else line


def decoded_payload(path: str, body: list[str], encoding: str | None, escaped: bool, trailing_newlines: int = 0) -> bytes:
    if encoding in (None, ''):
        text = '\n'.join(decode_text_line(line, escaped) for line in body)
        return (text.rstrip('\n') + '\n' * trailing_newlines).encode('utf-8')
    if encoding == 'base64':
        try:
            indented = bool(body) and all(line.startswith('    ') for line in body)
            chunks = [line[4:] if indented else line for line in body]
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
            trailing = int(attrs.get('trailing_newlines', '1' if encoding == '' and version != 'v2.0.0' else '0'))
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
                    # Legacy indentation is optional. Dedent only when the complete payload is indented.
                    escaped = bool(body) and all(item.startswith('    ') for item in body)
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


# ------------------------- Selection pipeline -------------------------
DEFAULT_EXCLUDES_VERSION = "2.1"
DEFAULT_EXCLUDES = (".DS_Store", "Thumbs.db", "*~", "*.swp", "*.swo", ".#*", "#*#")
TERMINAL_OUTCOMES = ("output_excluded", "protected", "hard_excluded", "positive_filter_missed", "soft_excluded", "invalid_object", "unreadable", "binary_skipped", "selected")

@dataclass(frozen=True)
class SourceProvenance:
    provider: str
    operand: str | None = None
    explicit: bool = False
    git_status: str | None = None
    git_source: str | None = None

@dataclass(frozen=True)
class Candidate:
    path: str
    absolute_path: Path
    provenance: tuple[SourceProvenance, ...]

@dataclass(frozen=True)
class PatternRule:
    provider: str
    pattern: str
    action: str
    order: int
    regex: re.Pattern[str]
    source: str | None = None
    line: int | None = None

@dataclass(frozen=True)
class ExtensionRule:
    provider: str
    suffix: str
    action: str
    order: int

@dataclass(frozen=True)
class RuleMatch:
    provider: str
    action: str
    pattern: str | None = None
    source: str | None = None
    line: int | None = None
    overrides: tuple[str, ...] = ()

@dataclass(frozen=True)
class PathDecision:
    candidate: Candidate
    matches: tuple[RuleMatch, ...]
    positive_filter_present: bool
    positive_filter_matched: bool
    explicit_selection_bases: tuple[str, ...]
    included: bool
    decisive_provider: str
    decisive_pattern: str | None
    terminal_outcome: str

@dataclass(frozen=True)
class ContentDecision:
    path_decision: PathDecision
    filesystem_kind: str | None
    content_kind: str | None
    data: bytes | None
    readonly: bool
    terminal_outcome: str

@dataclass(frozen=True)
class SelectionReport:
    context: "SelectionContext"
    decisions: tuple[ContentDecision, ...]
    filter_counts: dict[str, int]
    rule_match_counts: dict[str, int]
    providers: dict[str, dict[str, Any]]

@dataclass(frozen=True)
class NormalizedPackOptions:
    source: Path
    root: Path
    output: Path
    source_mode: str
    paths: tuple[str, ...]
    scopes: tuple[str, ...]
    only: tuple[str, ...]
    includes: tuple[PatternRule, ...]
    excludes: tuple[PatternRule, ...]
    force_includes: tuple[PatternRule, ...]
    include_extensions: tuple[ExtensionRule, ...]
    exclude_extensions: tuple[ExtensionRule, ...]
    ignore_files: tuple[Path, ...]
    no_gitignore: bool
    no_default_excludes: bool
    unsafe_include_git: bool
    binary_policy: str
    readonly: bool
    dry_run: bool
    json: bool
    explain: str | None
    quiet: bool
    verbose: bool
    force: bool

@dataclass(frozen=True)
class SelectionContext:
    options: NormalizedPackOptions
    selection_root: Path
    repository_root: Path | None
    output_resolved: Path | None


def _validate_pattern(raw: str, provider: str, order: int, action: str, source: str | None = None, line: int | None = None) -> PatternRule:
    if not raw or any(ch in raw for ch in ("\0", "\r", "\n")):
        raise UsageError(f"invalid empty or control-containing pattern: {raw!r}")
    if raw.startswith("!"):
        raise UsageError(f"leading ! is not supported for --{provider}; use an ignore file for negation")
    try:
        regex = re.compile(_wildmatch_regex(raw))
    except re.error as exc:
        raise UsageError(f"malformed pattern {raw!r}: {exc}") from exc
    return PatternRule(provider, raw, action, order, regex, source, line)


def _wildmatch_regex(pattern: str) -> str:
    anchored = pattern.startswith("/")
    directory = pattern.endswith("/")
    body = pattern[1:] if anchored else pattern
    if directory:
        body = body[:-1]
    if not body:
        raise re.error("pattern has no matchable content")
    out=[]; i=0
    while i < len(body):
        c=body[i]
        if c == "\\":
            i += 1
            if i >= len(body): raise re.error("trailing escape")
            out.append(re.escape(body[i]))
        elif c == "*":
            if i + 1 < len(body) and body[i+1] == "*":
                while i + 1 < len(body) and body[i+1] == "*": i += 1
                if i + 1 < len(body) and body[i+1] == "/":
                    i += 1; out.append("(?:.*/)?")
                else: out.append(".*")
            else: out.append("[^/]*")
        elif c == "?": out.append("[^/]")
        elif c == "[":
            j=i+1
            if j < len(body) and body[j] in "!^": j += 1
            if j < len(body) and body[j] == "]": j += 1
            while j < len(body) and body[j] != "]": j += 1
            if j >= len(body): raise re.error("unterminated bracket expression")
            stuff=body[i+1:j]
            if stuff.startswith("!"): stuff="^"+stuff[1:]
            out.append("["+stuff.replace("\\", "\\\\")+"]"); i=j
        else: out.append(re.escape(c))
        i += 1
    core="".join(out)
    prefix="^" if anchored or "/" in body else "(?:^|.*/)"
    suffix="(?:/.*)?$" if directory else "$"
    return prefix + core + suffix


def pattern_matches(path: str, rule: PatternRule) -> bool:
    return bool(rule.regex.match(path))


def normalize_extension(raw: str) -> str:
    value=raw.strip().lower()
    if not value or value == "." or any(ch in value for ch in ("/", "\\", "\0", "\r", "\n")):
        raise UsageError(f"invalid extension: {raw!r}")
    return value if value.startswith(".") else "."+value


def _inside(path: Path, root: Path) -> bool:
    try: path.relative_to(root); return True
    except ValueError: return False


def _operand(root: Path, raw: str) -> Path:
    lexical=Path(raw)
    if not lexical.is_absolute() and ".." in lexical.parts:
        raise UsageError(f"path operand contains lexical traversal: {raw}")
    path=lexical if lexical.is_absolute() else root/lexical
    resolved=path.resolve()
    if not _inside(resolved, root): raise UsageError(f"path is outside selection root: {raw}")
    return path


def _git(args: list[str], cwd: Path, stdin: bytes | None = None, accepted=(0,)) -> subprocess.CompletedProcess[bytes]:
    try: p=subprocess.run(["git", *args], cwd=cwd, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc: raise IOErrorDx("git executable is unavailable") from exc
    if p.returncode not in accepted:
        try: detail=p.stderr.decode("utf-8", "strict").strip()
        except UnicodeDecodeError as exc: raise IOErrorDx("git returned undecodable diagnostics") from exc
        raise IOErrorDx(f"git {' '.join(args)} failed ({p.returncode}): {detail}")
    return p


def _repository_root(start: Path) -> Path | None:
    p=_git(["rev-parse", "--is-inside-work-tree"], start, accepted=(0,128))
    if p.returncode != 0: return None
    if p.stdout.decode("ascii", "strict").strip() != "true": return None
    q=_git(["rev-parse", "--show-toplevel"], start)
    return Path(q.stdout.decode("utf-8", "strict").strip()).resolve()


def normalize_pack_options(a) -> NormalizedPackOptions:
    if a.binary and a.skip_binary: raise UsageError("--binary and --skip-binary are mutually exclusive")
    binary_policy=a.binary_policy or ("skip" if a.skip_binary else "include")
    if a.quiet and a.verbose: raise UsageError("--quiet and --verbose are mutually exclusive")
    if a.only and (a.path or a.from_git): raise UsageError("--only replaces candidate providers and cannot be combined with --path or --from-git")
    if a.unsafe_include_git and not a.force: raise UsageError("--unsafe-include-git requires --force")
    source_arg=a.source or (a.root if a.root else ".")
    source_lex=Path(source_arg)
    if source_lex.is_symlink(): source=source_lex.absolute()
    else: source=source_lex.resolve()
    if not source_lex.exists() and not source_lex.is_symlink(): raise IOErrorDx(f"source does not exist: {source_arg}")
    root=Path(a.root).resolve() if a.root else (source.parent if source_lex.is_file() or source_lex.is_symlink() else source.resolve())
    if not root.is_dir(): raise UsageError(f"selection root is not a directory: {root}")
    if not _inside(source.resolve(), root): raise UsageError("SOURCE is outside --root")
    output=Path(a.output_opt) if a.output_opt else resolve_default_output(a.source is None and a.root is None, source)
    if str(output) != "-" and not output.is_absolute(): output=Path.cwd()/output
    mode="only" if a.only else "git" if a.from_git else "path" if a.path else "file" if source_lex.is_file() or source_lex.is_symlink() else "walk"
    inc=tuple(_validate_pattern(x,"include",i,"include") for i,x in enumerate(a.include))
    for rule in inc:
        if rule.pattern.endswith("/"):
            raise UsageError(f"--include matches files, not directory operands: {rule.pattern!r}; use --scope or --only for a subtree")
    exc=tuple(_validate_pattern(x,"exclude",i,"exclude") for i,x in enumerate(a.exclude))
    force_inc=tuple(_validate_pattern(x,"force_include",i,"include") for i,x in enumerate(a.force_include))
    ie=tuple(ExtensionRule("include_extension",normalize_extension(x),"include",i) for i,x in enumerate(dict.fromkeys(a.include_extension)))
    ee=tuple(ExtensionRule("exclude_extension",normalize_extension(x),"exclude",i) for i,x in enumerate(dict.fromkeys(a.exclude_extension)))
    scopes=tuple(a.scope)
    for raw in scopes: _operand(root,raw)
    automatic_dxignore=root/".dxignore"
    ignore_paths=([automatic_dxignore] if automatic_dxignore.is_file() else []) + [_operand(root,x) for x in a.ignore_file]
    ignores=tuple(dict.fromkeys(ignore_paths))
    explain="json" if a.explain == "json" else ("human" if a.explain else None)
    return NormalizedPackOptions(source,root,output,mode,tuple(a.path),scopes,tuple(a.only),inc,exc,force_inc,ie,ee,ignores,bool(a.no_gitignore or a.no_ignore),bool(a.no_default_excludes or a.no_ignore),a.unsafe_include_git,binary_policy,a.readonly,a.dry_run or explain=="json",a.json or explain=="json",explain,a.quiet,a.verbose,a.force)


def build_selection_context(o: NormalizedPackOptions) -> SelectionContext:
    repo=_repository_root(o.root)
    out=None if o.output==Path("-") else o.output.resolve()
    return SelectionContext(o,o.root,repo,out)


def _walk(scope: Path, root: Path, unsafe: bool) -> list[Path]:
    found=[]
    def onerror(exc): raise IOErrorDx(f"directory traversal failed: {exc}")
    for directory, dirs, files in os.walk(scope, topdown=True, followlinks=False, onerror=onerror):
        d=Path(directory)
        dirs[:]=sorted(x for x in dirs if not (d/x).is_symlink() and (unsafe or x != ".git"))
        for name in sorted(files):
            p=d/name
            if not p.is_symlink(): found.append(p)
    return found


def _contribute(store: dict[str,list[SourceProvenance]], root: Path, path: Path, provenance: SourceProvenance) -> None:
    try: rel=path.absolute().relative_to(root).as_posix()
    except ValueError as exc: raise UsageError(f"discovered path is outside selection root: {path}") from exc
    safe_user_path(rel); store.setdefault(rel,[]).append(provenance)


def _git_status_candidates(ctx: SelectionContext, store: dict[str,list[SourceProvenance]]) -> None:
    if ctx.repository_root is None: raise IOErrorDx("--from-git requires a Git worktree")
    raw=_git(["status","--porcelain=v1","-z","--untracked-files=all"],ctx.repository_root).stdout
    records=raw.split(b"\0"); i=0
    while i < len(records):
        rec=records[i]; i+=1
        if not rec: continue
        try: text=rec.decode("utf-8","strict")
        except UnicodeDecodeError as exc: raise IOErrorDx("git status returned an undecodable path") from exc
        if len(text)<4 or text[2] != " ": raise IOErrorDx(f"malformed Git status record: {text!r}")
        status,path=text[:2],text[3:]; source_name=None
        if "D" in status: raise UsageError(f"deletions cannot be represented in a DX carrier: {path}")
        if status[0] in "RC" or status[1] in "RC":
            if i>=len(records) or not records[i]: raise IOErrorDx("malformed Git rename/copy record")
            source_name=records[i].decode("utf-8","strict"); i+=1
        absolute=(ctx.repository_root/Path(*PurePosixPath(path).parts)).absolute()
        resolved=absolute.resolve()
        if not _inside(resolved,ctx.selection_root): continue
        _contribute(store,ctx.selection_root,absolute,SourceProvenance("git",path,False,status,source_name))


def _within_scope(path: Path, scopes: tuple[Path, ...]) -> bool:
    resolved=path.resolve()
    return not scopes or any(_inside(resolved,scope.resolve()) for scope in scopes)

def discover_candidates(ctx: SelectionContext) -> tuple[Candidate,...]:
    o=ctx.options; store: dict[str,list[SourceProvenance]]={}
    scopes=tuple(_operand(o.root,raw) for raw in o.scopes)
    def add(path: Path, provenance: SourceProvenance) -> None:
        if _within_scope(path,scopes): _contribute(store,o.root,path,provenance)
    def add_operand(raw: str, provider: str) -> None:
        p=_operand(o.root,raw)
        if p.is_symlink(): add(p,SourceProvenance(provider,raw,False)); return
        if not p.exists(): raise IOErrorDx(f"selected path does not exist: {raw}")
        operand_is_directory=p.is_dir()
        paths=_walk(p,o.root,o.unsafe_include_git) if operand_is_directory else [p]
        explicit=provider=="only" or (provider=="path" and not operand_is_directory)
        for q in paths: add(q,SourceProvenance(provider,raw,explicit))
    if o.source_mode == "only":
        for raw in o.only: add_operand(raw,"only")
    else:
        if o.source_mode == "file": add(o.source,SourceProvenance("source",str(o.source),False))
        elif o.source_mode == "walk":
            for q in _walk(o.source,o.root,o.unsafe_include_git): add(q,SourceProvenance("walk",str(o.source),False))
        if o.source_mode == "git": _git_status_candidates(ctx,store)
        for raw in o.paths: add_operand(raw,"path")
        if scopes:
            store={path: provenance for path,provenance in store.items() if _within_scope(o.root/Path(*PurePosixPath(path).parts),scopes)}
    return tuple(Candidate(path,o.root/Path(*PurePosixPath(path).parts),tuple(store[path])) for path in sorted(store))

def _git_ignore(ctx: SelectionContext, candidates: tuple[Candidate,...]) -> dict[str,RuleMatch]:
    if ctx.options.no_gitignore or ctx.repository_root is None: return {}
    paths=[]; mapping={}
    for c in candidates:
        resolved=c.absolute_path.resolve()
        if _inside(resolved,ctx.repository_root):
            rel=resolved.relative_to(ctx.repository_root).as_posix(); paths.append(rel); mapping[rel]=c.path
    if not paths: return {}
    payload=b"".join(x.encode("utf-8")+b"\0" for x in paths)
    p=_git(["check-ignore","-z","--stdin","--verbose","--non-matching"],ctx.repository_root,payload,accepted=(0,1))
    fields=p.stdout.split(b"\0"); result={}
    if fields and fields[-1]==b"": fields.pop()
    if len(fields)%4: raise IOErrorDx("malformed NUL-delimited git check-ignore output")
    for i in range(0,len(fields),4):
        try: src,lineno,pattern,path=(x.decode("utf-8","strict") for x in fields[i:i+4])
        except UnicodeDecodeError as exc: raise IOErrorDx("git check-ignore returned undecodable output") from exc
        if src and pattern and not pattern.startswith("!"):
            result[mapping[path]]=RuleMatch("gitignore","exclude",pattern,src,int(lineno) if lineno.isdigit() else None)
    return result



def apply_gitignore_filter(
    root: Path,
    relative_paths: set[str],
) -> set[str]:
    """Compatibility adapter returning paths not excluded by Git rules."""
    repository_root = _repository_root(root)

    if repository_root is None or not relative_paths:
        return set(relative_paths)

    ordered = sorted(relative_paths)
    payload = b"".join(
        item.encode("utf-8") + b"\0"
        for item in ordered
    )

    completed = _git(
        [
            "check-ignore",
            "-z",
            "--stdin",
        ],
        repository_root,
        payload,
        accepted=(0, 1),
    )

    ignored = {
        item.decode("utf-8", "strict")
        for item in completed.stdout.split(b"\0")
        if item
    }

    return set(ordered) - ignored


def _parse_dxignore_line(raw: str) -> tuple[str,bool] | None:
    if not raw: return None
    escaped_hash=raw.startswith("\\#"); escaped_bang=raw.startswith("\\!")
    if raw.startswith("#") and not escaped_hash: return None
    value=raw
    while value.endswith(" ") and not value.endswith("\\ "): value=value[:-1]
    if escaped_hash or escaped_bang: value=value[1:]
    neg=value.startswith("!") and not escaped_bang
    pattern=value[1:] if neg else value
    return (pattern,neg) if pattern else None

def _ignore_file_rules(paths: tuple[Path,...], root: Path) -> tuple[PatternRule,...]:
    rules=[]; order=0
    for path in paths:
        try: lines=path.read_text(encoding="utf-8").splitlines()
        except (OSError,UnicodeError) as exc: raise IOErrorDx(f"cannot read ignore file {path}: {exc}") from exc
        try: base=path.resolve().parent.relative_to(root).as_posix()
        except ValueError as exc: raise UsageError(f"ignore file is outside selection root: {path}") from exc
        for number,raw in enumerate(lines,1):
            parsed=_parse_dxignore_line(raw)
            if parsed is None: continue
            pattern,neg=parsed
            if base != "." and not pattern.startswith("/"):
                pattern=f"{base}/{pattern}"
            rules.append(_validate_pattern(pattern,"ignore_file",order,"include" if neg else "exclude",str(path),number)); order+=1
    return tuple(rules)

def evaluate_paths(ctx: SelectionContext, candidates: tuple[Candidate,...]) -> tuple[PathDecision,...]:
    o=ctx.options; git_ignored=_git_ignore(ctx,candidates); ignore_rules=_ignore_file_rules(o.ignore_files,o.root)
    defaults=tuple(_validate_pattern(x,"default",i,"exclude") for i,x in enumerate(DEFAULT_EXCLUDES)) if not o.no_default_excludes else ()
    result=[]
    for c in candidates:
        matches=[]; bases=[]
        if ctx.output_resolved is not None and c.absolute_path.resolve()==ctx.output_resolved:
            result.append(PathDecision(c,(RuleMatch("output","exclude"),),bool(o.includes or o.include_extensions),False,(),False,"output",None,"output_excluded")); continue
        if not o.unsafe_include_git and ".git" in PurePosixPath(c.path).parts:
            result.append(PathDecision(c,(RuleMatch("protected","exclude",".git"),),bool(o.includes or o.include_extensions),False,(),False,"protected",".git","protected")); continue
        hard=[RuleMatch(r.provider,"exclude",r.pattern) for r in o.excludes if pattern_matches(c.path,r)]
        hard += [RuleMatch(r.provider,"exclude",r.suffix) for r in o.exclude_extensions if PurePosixPath(c.path).name.lower().endswith(r.suffix)]
        if hard:
            result.append(PathDecision(c,tuple(hard),bool(o.includes or o.include_extensions),False,(),False,hard[0].provider,hard[0].pattern,"hard_excluded")); continue
        force_positive=[RuleMatch(r.provider,"include",r.pattern) for r in o.force_includes if pattern_matches(c.path,r)]
        positive=[RuleMatch(r.provider,"include",r.pattern) for r in o.includes if pattern_matches(c.path,r)]
        positive += [RuleMatch(r.provider,"include",r.suffix) for r in o.include_extensions if PurePosixPath(c.path).name.lower().endswith(r.suffix)]
        present=bool(o.includes or o.include_extensions)
        for p in c.provenance:
            if p.explicit: bases.append(p.provider)
        bases.extend(m.provider for m in force_positive if m.provider not in bases)
        if present and not positive and not bases:
            result.append(PathDecision(c,(),True,False,(),False,"positive_filter",None,"positive_filter_missed")); continue
        matches.extend(positive)
        matches.extend(force_positive)
        soft=[]
        if c.path in git_ignored and not any(p.git_status and p.git_status != "??" for p in c.provenance): soft.append(git_ignored[c.path])
        current=None
        for r in ignore_rules:
            if pattern_matches(c.path,r): current=RuleMatch(r.provider,r.action,r.pattern,r.source,r.line)
        if current and current.action=="exclude": soft.append(current)
        soft.extend(RuleMatch(r.provider,"exclude",r.pattern) for r in defaults if pattern_matches(c.path,r))
        matches.extend(soft)
        if soft and not bases and not positive:
            decisive=soft[-1]; result.append(PathDecision(c,tuple(matches),present,bool(positive),tuple(dict.fromkeys(bases)),False,decisive.provider,decisive.pattern,"soft_excluded")); continue
        reason=positive[0] if positive else RuleMatch("explicit" if bases else "default_selection","include")
        result.append(PathDecision(c,tuple(matches),present,bool(positive),tuple(dict.fromkeys(bases)),True,reason.provider,reason.pattern,"selected"))
    return tuple(result)


def load_and_classify(ctx: SelectionContext, decisions: tuple[PathDecision,...]) -> tuple[ContentDecision,...]:
    out=[]
    for d in decisions:
        if not d.included:
            out.append(ContentDecision(d,None,None,None,ctx.options.readonly,d.terminal_outcome)); continue
        p=d.candidate.absolute_path
        if p.is_symlink() or not p.is_file():
            out.append(ContentDecision(d,"invalid",None,None,ctx.options.readonly,"invalid_object")); continue
        try:
            resolved=p.resolve(strict=True)
            if not _inside(resolved,ctx.selection_root):
                out.append(ContentDecision(d,"invalid",None,None,ctx.options.readonly,"invalid_object")); continue
            data=p.read_bytes()
        except OSError:
            out.append(ContentDecision(d,"regular",None,None,ctx.options.readonly,"unreadable")); continue
        kind=classify_file(data)
        if kind=="binary" and ctx.options.binary_policy=="skip": terminal="binary_skipped"
        elif kind=="binary" and ctx.options.binary_policy=="fail": terminal="invalid_object"
        else: terminal="selected"
        out.append(ContentDecision(d,"regular",kind,data if terminal=="selected" else None,ctx.options.readonly,terminal))
    return tuple(out)

def build_report(ctx: SelectionContext, decisions: tuple[ContentDecision,...]) -> SelectionReport:
    counts={k:0 for k in TERMINAL_OUTCOMES}; matches={k:0 for k in ("output","protected","exclude","exclude_extension","include","include_extension","force_include","gitignore","ignore_file","default")}
    for d in decisions:
        counts[d.terminal_outcome]+=1
        for m in d.path_decision.matches:
            if m.provider in matches: matches[m.provider]+=1
    assert len(decisions)==sum(counts.values())
    git_state="disabled_by_user" if ctx.options.no_gitignore else "unavailable_no_repository" if ctx.repository_root is None else "active"
    default_state="disabled_by_user" if ctx.options.no_default_excludes else "active"
    providers={
        "gitignore":{"state":git_state,"repository_root":str(ctx.repository_root) if ctx.repository_root else None,"matched":matches["gitignore"]},
        "dxignore":{"state":"active" if (ctx.options.root/".dxignore").is_file() else "not_applicable","path":str(ctx.options.root/".dxignore"),"matched":sum(1 for d in decisions for m in d.path_decision.matches if m.provider=="ignore_file" and m.source==str(ctx.options.root/".dxignore"))},
        "ignore_files":{"state":"active" if ctx.options.ignore_files else "not_applicable","paths":[str(x) for x in ctx.options.ignore_files],"matched":matches["ignore_file"]},
        "defaults":{"state":default_state,"version":DEFAULT_EXCLUDES_VERSION,"matched":matches["default"]},
    }
    return SelectionReport(ctx,decisions,counts,matches,providers)


def select_for_pack(ctx: SelectionContext) -> SelectionReport:
    return build_report(ctx,load_and_classify(ctx,evaluate_paths(ctx,discover_candidates(ctx))))

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
        lines = text_stripped.split('\n') if text_stripped else []
        escaped = any(line == '%%ENDBLOCK' for line in lines)
        if escaped:
            attrs.append('escaped="true"')
        if trailing:
            attrs.append(f'trailing_newlines="{trailing}"')
        h.write('%%FILE ' + ' '.join(attrs) + '\n')
        for line in lines:
            h.write((encode_text_line(line) if escaped else line) + '\n')
        h.write('%%ENDBLOCK\n')
        return True


def write_atomic(output: Path, force: bool, writer) -> None:
    if output == Path('-'):
        from io import StringIO

        buffer = StringIO(newline="\n")
        writer(buffer)
        sys.stdout.buffer.write(buffer.getvalue().encode("utf-8"))
        sys.stdout.buffer.flush()
        return
    # Termux exposes ~/storage/downloads through a directory symlink. Resolve
    # only the parent, while continuing to reject a symlink at the output file.
    if output.is_symlink():
        raise WriteConflictError(f"refusing to replace symlink: {output}")
    writable_output = output.parent.resolve() / output.name
    try:
        atomic_write_text(writable_output, writer, replace=force)
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


def _decision_json(decision: ContentDecision) -> dict[str,Any]:
    p=decision.path_decision
    return {"path":p.candidate.path,"included":decision.terminal_outcome=="selected","terminal_outcome":decision.terminal_outcome,"explicit_selection_bases":list(p.explicit_selection_bases),"decisive_reason":{"provider":p.decisive_provider,"pattern":p.decisive_pattern},"matches":[{"provider":m.provider,"pattern":m.pattern,"action":m.action,"source":m.source,"line":m.line,"overrides":list(m.overrides)} for m in p.matches]}


def pack_command(a) -> int:
    o=normalize_pack_options(a); ctx=build_selection_context(o); report=select_for_pack(ctx)
    selected=[d for d in report.decisions if d.terminal_outcome=="selected"]
    if o.explain=="human":
        for d in report.decisions:
            p=d.path_decision
            print(f"{p.candidate.path}  {'include' if d.terminal_outcome=='selected' else 'exclude'}  {p.decisive_provider}{' '+p.decisive_pattern if p.decisive_pattern else ''}",file=sys.stderr)
    if o.dry_run:
        if o.json:
            json.dump({"schema_version":3,"command":"pack","success":bool(selected),"errors":[] if selected else [{"code":"EmptySelectionError","message":_empty_message(report)}],"warnings":[],"empty_reason":None if selected else _empty_reason(report),"dry_run":True,"selection_root":str(ctx.selection_root),"source_mode":o.source_mode,"candidate_count":len(report.decisions),"filter_counts":report.filter_counts,"rule_match_counts":report.rule_match_counts,"providers":report.providers,"decisions":[_decision_json(d) for d in report.decisions],"selected_files":len(selected),"text_files":sum(d.content_kind=="text" and d.terminal_outcome=="selected" for d in report.decisions),"binary_files":sum(d.content_kind=="binary" and d.terminal_outcome=="selected" for d in report.decisions),"skipped_files":report.filter_counts["binary_skipped"],"files":[{"path":d.path_decision.candidate.path,"type":d.content_kind} for d in selected]},sys.stdout,indent=2);sys.stdout.write("\n")
        elif not o.quiet:
            print(f"DX carrier plan\nSource: {o.source}\nRoot: {o.root}\nOutput: {o.output if o.output!=Path('-') else 'stdout'}\n\nSelected files: {len(selected)}\nUTF-8 text files: {sum(d.content_kind=='text' for d in selected)}\nBinary files encoded as base64: {sum(d.content_kind=='binary' for d in selected)}\nGit-ignored files excluded: {report.rule_match_counts['gitignore']}\nDefault-excluded files: {report.rule_match_counts['default']}\nExplicitly excluded files: {report.filter_counts['hard_excluded']}\nUnreadable files: {report.filter_counts['unreadable']}\n\nNo files were written.",file=sys.stderr)
        if not selected:
            if o.json: return EmptySelectionError.exit_code
            raise EmptySelectionError(_empty_message(report))
        return 0
    if not selected: raise EmptySelectionError(_empty_message(report))
    if o.binary_policy == "skip" and not o.quiet:
        for d in report.decisions:
            if d.terminal_outcome == 'binary_skipped': print(f"Omitted non-UTF-8: {d.path_decision.candidate.path}", file=sys.stderr)
    def writer(h):
        h.write(f"%%DX {VERSION}\n")
        for d in selected: encode_entry(h,d.path_decision.candidate.path,d.data or b"",o.readonly)
        h.write("%%END\n")
    if o.output!=Path("-"): o.output.parent.mkdir(parents=True,exist_ok=True)
    existed=o.output.exists() if o.output!=Path("-") else False
    write_atomic(o.output,o.force,writer)
    if o.output!=Path("-"):
        if o.quiet: print(o.output)
        else: print(f"DX carrier {'replaced' if existed else 'created'}: {o.output}\nIncluded: {len(selected)} files\nSkipped non-UTF-8: {report.filter_counts['binary_skipped']} files\nNext: dx.py inspect \"{o.output}\"",file=sys.stderr)
    return 0


def _empty_reason(report: SelectionReport) -> str:
    if not report.decisions: return "no_candidates"
    if any(d.path_decision.included for d in report.decisions): return "all_content_excluded"
    return "all_path_excluded"

def _empty_message(report: SelectionReport) -> str:
    return _empty_reason(report).replace("_", " ")

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
    p.add_argument('-p', '--path', action='append', default=[], help='Add a file or recursively discovered directory to the candidate set (repeatable)')
    p.add_argument('-g', '--from-git', action='store_true', help='Add Git worktree changes to the candidate set')
    p.add_argument('--scope', action='append', default=[], metavar='PATH', help='Restrict all candidate providers to this file or subtree (repeatable)')
    p.add_argument('--only', action='append', default=[], metavar='PATH', help='Use only files discovered under these operands as candidates (repeatable)')
    p.add_argument('-i', '--include', action='append', default=[], help='Retain candidates matching PATTERN; does not override ignore rules (repeatable)')
    p.add_argument('-I', '--exclude', action='append', default=[], help='Unconditionally exclude paths matching PATTERN (repeatable)')
    p.add_argument('--force-include', action='append', default=[], metavar='PATTERN', help='Override ordinary ignore rules for matching candidates (repeatable)')
    p.add_argument('-x', '--include-extension', action='append', default=[], metavar='EXT', help='Include only files with extension')
    p.add_argument('-X', '--exclude-extension', action='append', default=[], metavar='EXT', help='Exclude files with extension')
    p.add_argument('-b', '--binary', action='store_true', help='Deprecated alias for --binary-policy include')
    p.add_argument('--binary-policy', choices=('include','skip','fail'), help='Policy for non-UTF-8 or non-LF content')
    p.add_argument('-B', '--skip-binary', action='store_true', help='Skip non-UTF-8 files')
    p.add_argument('--readonly', action='store_true', help='Mark all entries as read-only')
    p.add_argument('-G', '--no-gitignore', action='store_true', help='Do not apply Git ignore rules')
    p.add_argument('--no-default-excludes', action='store_true', help='Do not apply default excludes')
    p.add_argument('--ignore-file', action='append', default=[], metavar='FILE', help='Apply ordered DX ignore rules; automatic ROOT/.dxignore is evaluated first (repeatable)')
    p.add_argument('--no-ignore', action='store_true', help='Disable Git-ignore and default excludes')
    p.add_argument('--unsafe-include-git', action='store_true', help='Disable only protected .git exclusion; requires --force')
    p.add_argument('--explain', nargs='?', const='human', choices=('human','json'), help='Explain every candidate; json implies --dry-run --json')
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
    insp.add_argument('-c', '--cat', '--file', dest='cat', metavar='PATH', help='Write file content to stdout')
    insp.add_argument('-C', '--compare', '--compare-root', dest='compare', metavar='DIR', help='Compare carrier with directory')
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

    commands = {'pack', 'p', 'unpack', 'u', 'apply', 'a', 'inspect'}
    if (len(normalized_args) >= 2 and normalized_args[0] in commands
            and normalized_args[1] == normalized_args[0]):
        print(
            f"WARNING: duplicate command {normalized_args[0]!r} ignored; "
            "update the alias to invoke dx.py without a command.",
            file=sys.stderr,
        )
        normalized_args.pop(1)

    parser = build_parser()
    a = None
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
            if not a.dry_run and a.output_opt and a.output_opt != "-":
                output = Path(a.output_opt)
                if not output.is_absolute():
                    output = Path.cwd() / output
                if output.is_symlink():
                    raise WriteConflictError(f"refusing to replace symlink: {output}")
                if output.exists() and not a.force:
                    raise WriteConflictError(f"output already exists; use --force to replace it: {output}")

        return a.func(a)
    except InvalidCarrierError as e:
        if a is not None and hasattr(a, 'command') and a.command == 'inspect' and getattr(a, 'json', False):
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
        command = a.command if a is not None and hasattr(a, 'command') else None
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
        if a is not None and getattr(a, "command", None) in ("pack","p") and getattr(a, "json", False):
            json.dump({"schema_version":3,"command":"pack","success":False,"errors":[{"code":type(e).__name__,"message":str(e)}],"warnings":[],"dry_run":bool(getattr(a,"dry_run",False)),"empty_reason":str(e).replace(" ","_") if isinstance(e,EmptySelectionError) else None},sys.stdout,indent=2);sys.stdout.write("\n")
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        command = a.command if a is not None and hasattr(a, 'command') else None
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