#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
(($#)) || usage_error 'Usage: dx-inspect.sh CARRIER [--list|--hashes|--readonly|--file PATH]'
carrier=$1; shift; [[ -f "$carrier" ]] || die "carrier not found: $carrier"; mode=summary; wanted=''
while (($#)); do case "$1" in --list) mode=list;; --hashes) mode=hashes;; --readonly) mode=readonly;; --file) shift; (($#)) || usage_error '--file requires a path'; mode=file; wanted=$1;; -h|--help) echo 'Usage: dx-inspect.sh CARRIER [--list|--hashes|--readonly|--file PATH]'; exit 0;; *) usage_error "unknown argument: $1";; esac; shift; done
require_cmd python3
python3 - "$carrier" "$mode" "$wanted" <<'PY'
import sys,re,hashlib
p,mode,wanted=sys.argv[1:]; data=open(p,'rb').read()
try: text=data.decode('utf-8')
except UnicodeDecodeError as e: raise SystemExit(f'ERROR: not UTF-8: {e}')
lines=text.splitlines(keepends=True); version='headerless'; files=[]; notes=0; i=0
attr=re.compile(r'(\w+)="([^"]*)"')
while i<len(lines):
 s=lines[i].rstrip('\r\n')
 if s.startswith('%%DX'): version=s[4:].strip() or 'unspecified'; i+=1; continue
 if s.startswith('%%END') and s!='%%ENDBLOCK': break
 if s.startswith('%%NOTE'):
  notes+=1; i+=1
  while i<len(lines) and lines[i].rstrip('\r\n')!='%%ENDBLOCK': i+=1
  if i==len(lines): raise SystemExit('ERROR: unterminated NOTE block')
  i+=1; continue
 if s.startswith('%%FILE'):
  a=dict(attr.findall(s)); path=a.get('path');
  if not path: raise SystemExit(f'ERROR: FILE without path at physical line {i+1}')
  i+=1; payload=[]
  while i<len(lines) and lines[i].rstrip('\r\n')!='%%ENDBLOCK': payload.append(lines[i]); i+=1
  if i==len(lines): raise SystemExit(f'ERROR: unterminated FILE block: {path}')
  raw=''.join(payload)
  if raw.endswith('\r\n'): raw=raw[:-2]
  elif raw.endswith('\n') or raw.endswith('\r'): raw=raw[:-1]
  files.append((path,a,raw)); i+=1; continue
 i+=1
if mode=='summary':
 print(f'DX version: {version}\nFile count: {len(files)}\nNOTE blocks: {notes}')
 for path,a,raw in files: print(f'{path}\treadonly={a.get("readonly","false")}\tsha256={hashlib.sha256(raw.encode()).hexdigest()}')
elif mode=='list':
 for x in files: print(x[0])
elif mode=='hashes':
 for path,a,raw in files: print(hashlib.sha256(raw.encode()).hexdigest(),path)
elif mode=='readonly':
 for path,a,raw in files:
  if a.get('readonly','false').lower()=='true': print(path)
elif mode=='file':
 for path,a,raw in files:
  if path==wanted: sys.stdout.write(raw); sys.exit(0)
 raise SystemExit(f'ERROR: path not found: {wanted}')
PY