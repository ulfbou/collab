#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cp "$HERE/collab-state.py" "$TMP/"
cd "$TMP"

git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/profile-security.git

git rev-parse --is-inside-work-tree >/dev/null
git remote get-url origin >/dev/null
test -f collab-state.py

printf 'x\n' > tracked
git add tracked
git commit -qm init
pass(){ printf 'PASS: %s\n' "$1"; }
python3 collab-state.py save session --json '{"branch":"test/security"}'
profile=.dx/collab/profiles/session.json
python3 - <<'PY'
import json
p='.dx/collab/profiles/session.json';o=json.load(open(p));o['unexpected']=True;open(p,'w').write(json.dumps(o))
PY
chmod 600 "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass unknown-top-level-rejected
rm -f "$profile"; python3 collab-state.py save session --json '{"branch":"test/security"}'
python3 - <<'PY'
import json
p='.dx/collab/profiles/session.json';o=json.load(open(p));o['values']['unexpected']='x';open(p,'w').write(json.dumps(o))
PY
chmod 600 "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass unknown-value-rejected
rm -f "$profile"; python3 collab-state.py save session --json '{"branch":"test/security"}'
python3 - <<'PY'
import json
p='.dx/collab/profiles/session.json';o=json.load(open(p));o['schemaVersion']='2.0';open(p,'w').write(json.dumps(o))
PY
chmod 600 "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass wrong-schema-rejected
rm -f "$profile"; python3 collab-state.py save session --json '{"branch":"test/security"}'
python3 - <<'PY'
import json
p='.dx/collab/profiles/session.json';o=json.load(open(p));o['repository']='other/repository';open(p,'w').write(json.dumps(o))
PY
chmod 600 "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass wrong-repository-rejected
rm -f "$profile"; printf 'owned\n' > target; ln -s ../../../target "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass symlink-rejected
rm -f "$profile"; python3 collab-state.py save session --json '{"branch":"$(touch injected)"}'; [[ ! -e injected ]]; [[ $(python3 collab-state.py load session | python3 -c 'import json,sys;print(json.load(sys.stdin)["branch"])') == '$(touch injected)' ]]; [[ ! -e injected ]]; pass command-text-inert
if [[ $(uname -s) != MINGW* && $(uname -s) != MSYS* && $(uname -s) != CYGWIN* ]]; then chmod 644 "$profile"; ! python3 collab-state.py load session >/dev/null 2>&1; pass permissive-mode-rejected; fi