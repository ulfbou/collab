#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, subprocess, tempfile
from pathlib import Path, PurePosixPath

class Error(Exception): pass

def run(*args:str)->bytes:
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if p.returncode: raise Error(p.stderr.decode(errors='replace').strip() or f"command failed: {' '.join(args)}")
    return p.stdout

def safe_path(raw:str)->str:
    if '\x00' in raw or '"' in raw or '\\' in raw: raise Error(f'unrepresentable path: {raw}')
    p=PurePosixPath(raw)
    if p.is_absolute() or not p.parts or str(p)=='.' or '..' in p.parts: raise Error(f'unsafe path: {raw}')
    return str(p)

def read_payload(path:Path,name:str)->bytes:
    if path.is_symlink() or not path.is_file(): raise Error(f'missing or unsafe input: {name}')
    data=path.read_bytes()
    if data.startswith(b'\xef\xbb\xbf'): raise Error(f'UTF-8 BOM is not allowed: {name}')
    if b'\x00' in data: raise Error(f'binary content is not allowed: {name}')
    try: data.decode('utf-8')
    except UnicodeDecodeError as e: raise Error(f'input is not UTF-8: {name}: {e}')
    if b'\r' in data: raise Error(f'CR or CRLF line endings are not allowed: {name}')
    if data and not data.endswith(b'\n'): raise Error(f'final newline is required: {name}')
    return data

def changed_paths()->list[str]:
    raw=run('git','status','--porcelain=v1','-z','--untracked-files=all')
    entries=raw.split(b'\0'); result=[]; i=0
    while i < len(entries):
        entry=entries[i]
        if not entry: i+=1; continue
        text=entry.decode('utf-8'); status=text[:2]; name=text[3:]
        if 'D' in status: raise Error(f'deletions cannot be represented in a DX carrier: {name}')
        if status[0] in 'RC':
            i+=1
            if i>=len(entries) or not entries[i]: raise Error('malformed git rename record')
            name=entries[i].decode('utf-8')
        if name not in result: result.append(name)
        i+=1
    return sorted(result)

def pack(names:list[str])->bytes:
    if not names: raise Error('no files selected')
    out=[b'%%DX v1.3.1\n']
    seen=set()
    for raw in sorted(names):
        name=safe_path(raw)
        if name in seen: continue
        seen.add(name); data=read_payload(Path(name),name)
        out.append(f'%%FILE path="{name}"\n'.encode())
        for line in data.splitlines(keepends=True): out.append(b'    '+line)
        out.append(b'%%ENDBLOCK\n')
    out.append(b'%%END\n')
    return b''.join(out)

def atomic_write(path:Path,data:bytes)->None:
    if path.is_symlink(): raise Error(f'refusing to replace symlink: {path}')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.tmp.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); p.add_argument('--path',action='append',default=[]); p.add_argument('--from-git',action='store_true')
    a=p.parse_args()
    try:
        if a.from_git and a.path: raise Error('--from-git and --path are mutually exclusive')
        names=changed_paths() if a.from_git else a.path
        atomic_write(Path(a.out),pack(names)); print(a.out); return 0
    except Error as e:
        print(f'ERROR: {e}',file=__import__('sys').stderr); return 1
if __name__=='__main__': raise SystemExit(main())