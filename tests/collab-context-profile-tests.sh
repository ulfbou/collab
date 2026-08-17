#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-context-collect.sh" "$HERE/collab-profile-clear.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$TMP/"
chmod +x "$TMP/"*.sh "$TMP/collab-state.py"
cd "$TMP"
git init -q; git config user.name Test; git config user.email test@example.invalid
git remote add origin https://github.com/example/context-profile.git
printf 'base\n' > tracked; git add tracked; git commit -qm init

profile=.dx/collab/profiles/context.json

bash ./collab-context-collect.sh --role lead --no-github --no-files >/dev/null
test -s .dx/lead-context.md
bash ./collab-context-collect.sh --role senior --no-github --no-files >/dev/null
test -s .dx/senior-context.md
jq -e '.values.role == "senior" and .values.out == ".dx/senior-context.md"' "$profile" >/dev/null
printf 'PASS: lead to senior uses role-specific default output\n'

bash ./collab-profile-clear.sh context
bash ./collab-context-collect.sh --role senior --no-github --no-files >/dev/null
bash ./collab-context-collect.sh --role lead --no-github --no-files >/dev/null
jq -e '.values.role == "lead" and .values.out == ".dx/lead-context.md"' "$profile" >/dev/null
printf 'PASS: senior to lead uses role-specific default output\n'

bash ./collab-context-collect.sh --role lead --out .dx/custom-lead.md --no-github --no-files >/dev/null
bash ./collab-context-collect.sh --role lead --no-github --no-files >/dev/null
jq -e '.values.out == ".dx/custom-lead.md"' "$profile" >/dev/null
printf 'PASS: same-role profile reload preserves explicit custom output\n'

bash ./collab-context-collect.sh --role senior --no-github --no-files >/dev/null
jq -e '.values.out == ".dx/senior-context.md"' "$profile" >/dev/null
printf 'PASS: role switch does not inherit remembered custom output\n'

jq -e '.values.includes == [] and .values.excludes == [] and .values.consumerIncludes == []' "$profile" >/dev/null
printf 'PASS: empty context collections persist as empty arrays\n'

python3 - <<'PY2'
import json
from pathlib import Path
p=Path('.dx/collab/profiles/context.json')
o=json.loads(p.read_text(encoding='utf-8'))
o['values']['includes']=['']
p.write_text(json.dumps(o)+'\n', encoding='utf-8')
PY2
chmod 600 "$profile" 2>/dev/null || true
! python3 collab-state.py load context >/dev/null 2>&1
printf 'PASS: malformed empty context paths are rejected on reload\n'

! bash ./collab-context-collect.sh --no-github --no-files >/dev/null 2>&1
printf 'PASS: role remains an explicit required command argument\n'
