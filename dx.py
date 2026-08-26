#!/usr/bin/env python3
"""Canonical DX v1.3.1 carrier codec and CLI."""
from __future__ import annotations
import argparse, base64, binascii, fnmatch, hashlib, os, re, subprocess, sys, tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TextIO

VERSION = "v1.3.1"
DEVICE_DIR = Path("~/storage/downloads/DX").expanduser()

def device_output_dir() -> Path:
    override = os.environ.get("DX_DEVICE_DIR")
    return Path(override).expanduser() if override else DEVICE_DIR
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
NUMBERED_RE = re.compile(r'^dx-carrier-(\d+)\.dx\.txt$')

class DxError(ValueError): pass

@dataclass(frozen=True)
class Entry:
    path: str
    data: bytes
    readonly: bool = False
    encoding: str | None = None

def safe_path(raw: str) -> str:
    value=raw.replace('\\','/'); parts=value.split('/')
    if (not value or value.startswith('/') or '"' in value or '\0' in value or '\n' in value or '\r' in value or any(x in ('','.','..') for x in parts)):
        raise DxError(f"unsafe path: {raw!r}")
    return PurePosixPath(value).as_posix()

def normalize_text(text: str) -> str:
    return text.replace('\r\n','\n').replace('\r','\n').rstrip('\n')

def encode_text_line(line: str) -> str:
    return ('        ' if line.startswith('%%') else '    ')+line

def decode_text_line(line: str) -> str:
    if not line.startswith('    '): raise DxError(f"unindented text payload line: {line!r}")
    line=line[4:]
    return line[4:] if line.startswith('    %%') else line

def decoded_payload(path: str, body: list[str], encoding: str | None) -> bytes:
    if encoding in (None,''):
        text='\n'.join(decode_text_line(x) for x in body)
        return (text.rstrip('\n')+'\n').encode('utf-8')
    if encoding == 'base64':
        try:
            chunks=[]
            for line in body:
                if not line.startswith('    '): raise DxError(f"unindented base64 payload line: {path}")
                chunks.append(line[4:])
            return base64.b64decode(''.join(chunks),validate=True)
        except (binascii.Error,ValueError) as exc: raise DxError(f"invalid base64 payload: {path}") from exc
    raise DxError(f"unsupported encoding {encoding!r}: {path}")

def parse(source: TextIO) -> tuple[str,list[Entry],int]:
    lines=source.read().replace('\r\n','\n').replace('\r','\n').split('\n')
    version='unversioned'; entries=[]; notes=0; seen=set(); i=0
    while i<len(lines):
        line=lines[i]
        if line.startswith('%%DX'):
            parts=line.split(); version=parts[1] if len(parts)>1 else 'unknown'; i+=1; continue
        if line=='%%END': break
        if line.startswith('%%NOTE'):
            notes+=1; i+=1
            while i<len(lines) and lines[i]!='%%ENDBLOCK': i+=1
            if i>=len(lines): raise DxError('unterminated NOTE block')
            i+=1; continue
        if line.startswith('%%FILE'):
            attrs=dict(ATTR_RE.findall(line))
            if 'path' not in attrs: raise DxError(f"FILE without path at line {i+1}")
            path=safe_path(attrs['path'])
            if path in seen: raise DxError(f"duplicate path: {path}")
            seen.add(path); i+=1; body=[]
            while i<len(lines) and lines[i]!='%%ENDBLOCK': body.append(lines[i]); i+=1
            if i>=len(lines): raise DxError(f"unterminated file block: {path}")
            enc=attrs.get('encoding'); entries.append(Entry(path,decoded_payload(path,body,enc),attrs.get('readonly','false').lower()=='true',enc)); i+=1; continue
        if line: raise DxError(f"unexpected line {i+1}: {line}")
        i+=1
    return version,entries,notes

def read_entries(path: str):
    if path=='-': return parse(sys.stdin)
    p=Path(path)
    if not p.is_file(): raise DxError(f"carrier does not exist: {path}")
    with p.open('r',encoding='utf-8',newline='') as f: return parse(f)

def match_pattern(path:str,pattern:str)->bool:
    pattern=pattern.replace('\\','/').removeprefix('./').rstrip('/')
    if not pattern:return False
    prefixes=[path]+['/'.join(PurePosixPath(path).parts[:i]) for i in range(1,len(PurePosixPath(path).parts))]
    return any(x==pattern or x.startswith(pattern+'/') or fnmatch.fnmatchcase(x,pattern) or ('/' not in pattern and fnmatch.fnmatchcase(PurePosixPath(x).name,pattern)) for x in prefixes)

def selected(path,includes,excludes): return (not includes or any(match_pattern(path,x) for x in includes)) and not any(match_pattern(path,x) for x in excludes)

def git_changed_paths(root:Path)->list[str]:
    p=subprocess.run(['git','status','--porcelain=v1','-z','--untracked-files=all'],cwd=root,check=True,stdout=subprocess.PIPE)
    rec=p.stdout.split(b'\0'); out=[]; i=0
    while i<len(rec):
        r=rec[i]; i+=1
        if not r: continue
        s=r.decode('utf-8','strict'); status,path=s[:2],s[3:]
        if 'D' in status: raise DxError(f"deletions cannot be represented in a DX carrier: {path}")
        if status[0] in 'RC' or status[1] in 'RC':
            if i>=len(rec) or not rec[i]: raise DxError(f"malformed git rename/copy record: {path}")
            path=rec[i].decode('utf-8','strict'); i+=1
        out.append(safe_path(path))
    return sorted(set(out))


def git_ignored_paths(path: Path, names: list[str]) -> set[str]:
    if not names:
        return set()

    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return set()

    if probe.returncode != 0:
        return set()

    repository_root = Path(probe.stdout.strip()).resolve()
    repository_names: list[str] = []

    for name in names:
        absolute = (path / Path(*PurePosixPath(name).parts)).resolve()
        try:
            relative = absolute.relative_to(repository_root).as_posix()
        except ValueError as exc:
            raise DxError(
                f"path is outside Git repository during .gitignore evaluation: {name}"
            ) from exc
        repository_names.append(relative)

    payload = b"\0".join(
        name.encode("utf-8", "strict")
        for name in repository_names
    ) + b"\0"

    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z", "--no-index"],
        cwd=repository_root,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode not in (0, 1):
        message = result.stderr.decode("utf-8", "replace").strip()
        suffix = f": {message}" if message else ""
        raise DxError(f"failed to evaluate .gitignore{suffix}")

    ignored_repository_paths = {
        safe_path(item.decode("utf-8", "strict"))
        for item in result.stdout.split(b"\0")
        if item
    }

    return {
        name
        for name, repository_name in zip(names, repository_names)
        if repository_name in ignored_repository_paths
    }

def collect_paths(root:Path,source:Path,explicit:list[str],from_git:bool,includes,excludes,output:Path|None,device:bool)->list[str]:
    if explicit and from_git: raise DxError('--path and --from-git are mutually exclusive')
    if from_git: names=git_changed_paths(root)
    elif explicit:
        names=[]
        for raw in explicit:
            c=(root/raw)
            if not c.exists(): raise DxError(f"selected path does not exist: {raw}")
            names += [p.relative_to(root).as_posix() for p in c.rglob('*') if p.is_file()] if c.is_dir() else [c.relative_to(root).as_posix()]
    else:
        names=[p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file() and not p.is_symlink()]
        if device: excludes=[*excludes,'.git','.dx']
    output_resolved=output.resolve() if output else None; result=set()
    for name in names:
        rel=safe_path(name)
        actual=(root/rel) if (from_git or explicit) else (source/rel)
        if output_resolved and actual.resolve()==output_resolved: continue
        if selected(rel,includes,excludes): result.add(rel)

    if device:
        result.difference_update(
            git_ignored_paths(root, sorted(result))
        )

    return sorted(result)

def next_device_output(force:bool)->Path:
    directory=device_output_dir()
    directory.mkdir(parents=True,exist_ok=True)
    if force:return directory/'dx-carrier.dx.txt'
    highest=0
    for p in directory.iterdir():
        m=NUMBERED_RE.fullmatch(p.name)
        if m: highest=max(highest,int(m.group(1)))
    return directory/f'dx-carrier-{highest+1}.dx.txt'

def encode_entry(h,path,data,readonly,include_binary,omit_binary):
    attrs=[f'path="{safe_path(path)}"']
    if readonly: attrs.append('readonly="true"')
    if data.startswith(b'\xef\xbb\xbf'): raise DxError(f'UTF-8 BOM is not permitted: {path}')
    binary = b'\0' in data
    try:text=data.decode('utf-8') if not binary else None
    except UnicodeDecodeError:text=None
    if text is None:
        if not include_binary:
            if omit_binary: print(f"Omitted non-UTF-8: {path}",file=sys.stderr); return False
            raise DxError(f"non-UTF-8 file requires --include-non-utf8 or --omit-non-utf8: {path}")
        attrs.append('encoding="base64"'); h.write('%%FILE '+' '.join(attrs)+'\n    '+base64.b64encode(data).decode('ascii')+'\n%%ENDBLOCK\n'); return True
    h.write('%%FILE '+' '.join(attrs)+'\n'); text=normalize_text(text)
    if text:
        for line in text.split('\n'): h.write(encode_text_line(line)+'\n')
    h.write('%%ENDBLOCK\n'); return True

def write_atomic(output:Path,force:bool,writer):
    if output.is_symlink(): raise DxError(f"refusing to replace symlink: {output}")
    if output.exists() and not force: raise DxError(f"output already exists; use --force to replace it: {output}")
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=output.name+'.tmp.',dir=output.parent,text=True); os.close(fd)
    try:
        with open(tmp,'w',encoding='utf-8',newline='\n') as h: writer(h); h.flush(); os.fsync(h.fileno())
        if not force:
            lock = output.with_name(output.name + ".lock")
            lock_fd = None
            try:
                try:
                    lock_fd = os.open(
                        lock,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                except FileExistsError:
                    raise DxError(
                        f"output is currently being created: {output}"
                    )

                if output.exists():
                    raise DxError(
                        "output already exists; use --force to replace it: "
                        f"{output}"
                    )

                os.replace(tmp, output)
            finally:
                if lock_fd is not None:
                    os.close(lock_fd)
                try:
                    os.unlink(lock)
                except FileNotFoundError:
                    pass
        else:
            os.replace(tmp,output)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def pack_command(a):
    if a.include_non_utf8 and a.omit_non_utf8: raise DxError('--include-non-utf8 and --omit-non-utf8 are mutually exclusive')
    source_arg=a.source or (a.root if a.root else '.'); source=Path(source_arg).resolve()
    root=Path(a.root).resolve() if a.root else source
    if not source.is_dir(): raise DxError(f"source directory does not exist: {source_arg}")
    explicit_output=a.out or a.output
    device=not explicit_output and not a.from_git and not a.path and not a.root
    output=Path(explicit_output) if explicit_output else next_device_output(a.force)
    if not output.is_absolute(): output=Path.cwd()/output
    omit=not a.include_non_utf8 or device
    names=collect_paths(root,source,a.path,a.from_git,a.include,a.exclude,output,device)
    if not names: raise DxError('no files selected')
    count=omitted=0
    def writer(h):
        nonlocal count,omitted
        h.write(f'%%DX {VERSION}\n')
        for name in names:
            target=(root/name) if (a.path or a.from_git or a.root) else (source/name)
            if target.is_symlink() or not target.is_file(): raise DxError(f"selected path is not a regular file: {name}")
            if encode_entry(h,name,target.read_bytes(),a.readonly,a.include_non_utf8,omit): count+=1
            else: omitted+=1
        if not count: raise DxError('no representable files selected')
        h.write('%%END\n')
    existed=output.exists(); write_atomic(output,a.force,writer)
    if a.quiet: print(output)
    else:
        print(('Replaced' if existed else 'Created')+f': {output}')
        print(f'Files: {count}'); print(f'Omitted non-UTF-8: {omitted}')
    return 0

def apply_command(a):
    _,entries,_=read_entries(a.carrier); root=Path(a.destination).resolve(); root.mkdir(parents=True,exist_ok=True)
    for e in entries:
        if e.readonly: continue
        target=(root/Path(*PurePosixPath(e.path).parts)).resolve()
        if target!=root and root not in target.parents: raise DxError(f"path escapes destination: {e.path}")
        if target.exists() and not a.force: print(f"Skipped existing: {e.path}",file=sys.stderr); continue
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(e.data)
    return 0

def inspect_command(a):
    version,entries,notes=read_entries(a.carrier)
    if a.list:
        for e in entries: print(e.path)
    elif a.hashes:
        for e in entries: print(hashlib.sha256(e.data).hexdigest(),e.path)
    elif a.readonly:
        for e in entries:
            if e.readonly: print(e.path)
    elif a.file is not None:
        m=[e for e in entries if e.path==a.file]
        if len(m)!=1: raise DxError(f"expected exactly one file named {a.file!r}, found {len(m)}")
        sys.stdout.buffer.write(m[0].data)
    elif a.compare_root is not None:
        root=Path(a.compare_root).resolve(); bad=0
        for e in entries:
            p=root/Path(*PurePosixPath(e.path).parts)
            if not p.is_file() or p.read_bytes()!=e.data: print(e.path); bad+=1
        return 1 if bad else 0
    else:
        print(f'DX version: {version}\nFile count: {len(entries)}\nNOTE blocks: {notes}')
        for e in entries: print(f"{e.path}\treadonly={'true' if e.readonly else 'false'}\tsha256={hashlib.sha256(e.data).hexdigest()}")
    return 0

TOP_HELP='''DX v1.3.1 carrier utility

Usage:
  dx.py COMMAND [arguments]

Commands:
  pack       Pack files into a DX carrier
  unpack     Unpack a DX carrier
  apply      Alias for unpack
  inspect    Inspect paths, hashes, and metadata

Quick start:
  dx.py pack
  dx.py pack --force
  dx.py unpack ~/storage/downloads/DX/dx-carrier.dx.txt
  dx.py inspect ~/storage/downloads/DX/dx-carrier.dx.txt --list

Run "dx.py COMMAND -h" for command-specific help.
'''
class Parser(argparse.ArgumentParser):
    def error(self,message): raise DxError(message)

def parser():
    top=Parser(prog='dx.py',add_help=False); top.add_argument('-h','--help',action='store_true'); sub=top.add_subparsers(dest='command')
    p=sub.add_parser('pack',aliases=['p'],help='Pack files into a DX carrier',formatter_class=argparse.RawDescriptionHelpFormatter,description='Pack files. With no arguments, pack the current directory to the next lowercase numbered carrier in ~/storage/downloads/DX.')
    p.add_argument('source',nargs='?',metavar='SOURCE'); p.add_argument('output',nargs='?',metavar='OUTPUT'); p.add_argument('--out'); p.add_argument('--root'); p.add_argument('--path',action='append',default=[],help='advanced: exact file or folder, repeatable'); p.add_argument('--from-git',action='store_true',help='advanced: current Git changes'); p.add_argument('--include',action='append',default=[]); p.add_argument('--exclude',action='append',default=[]); p.add_argument('--include-non-utf8',action='store_true'); p.add_argument('--omit-non-utf8',action='store_true'); p.add_argument('--readonly',action='store_true'); p.add_argument('-f','--force',action='store_true'); p.add_argument('--quiet',action='store_true'); p.set_defaults(func=pack_command)
    for name,aliases in [('unpack',['u']),('apply',['a'])]:
        q=sub.add_parser(name,aliases=aliases); q.add_argument('carrier',metavar='CARRIER'); q.add_argument('destination',nargs='?',default='.',metavar='DESTINATION'); q.add_argument('-f','--force',action='store_true'); q.set_defaults(func=apply_command)
    q=sub.add_parser('inspect'); q.add_argument('carrier',metavar='CARRIER'); m=q.add_mutually_exclusive_group(); m.add_argument('--list',action='store_true');m.add_argument('--hashes',action='store_true');m.add_argument('--readonly',action='store_true');m.add_argument('--file');m.add_argument('--compare-root');q.set_defaults(func=inspect_command)
    return top

def usage_for(command):
    return {'pack':'  dx.py pack [SOURCE] [OUTPUT] [options]','unpack':'  dx.py unpack CARRIER [DESTINATION] [options]','apply':'  dx.py apply CARRIER [DESTINATION] [options]','inspect':'  dx.py inspect CARRIER [options]'}.get(command,'  dx.py COMMAND [arguments]')
def main(argv=None):
    argsv=list(sys.argv[1:] if argv is None else argv)
    if not argsv: print(TOP_HELP,end=''); return 0
    if argsv in (['-h'],['--help']): print(TOP_HELP,end=''); return 0
    command=argsv[0] if argsv and argsv[0] in ('pack','p','unpack','u','apply','a','inspect') else None
    canonical={'p':'pack','u':'unpack','a':'apply'}.get(command,command)
    try:
        a=parser().parse_args(argsv)
        if getattr(a,'help',False): print(TOP_HELP,end=''); return 0
        if not hasattr(a,'func'): print(TOP_HELP,end=''); return 0
        return a.func(a)
    except (DxError,OSError,UnicodeError,subprocess.CalledProcessError) as e:
        print(f'ERROR: {canonical+": " if canonical and str(e).startswith("argument") else ""}{e}',file=sys.stderr)
        print('Usage:\n'+usage_for(canonical),file=sys.stderr)
        if canonical: print(f'Run "dx.py {canonical} -h" for complete help.',file=sys.stderr)
        return 1
if __name__=='__main__': raise SystemExit(main())