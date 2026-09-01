#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/ulfbou/mock-repo.git
printf 'base\n' > tracked
git add tracked
git commit -qm init

profile=.dx/collab/profiles/context.json

bash "$HERE/collab-context-collect.sh" --role lead --no-github --no-files >/dev/null
test -s .dx/lead-context.md

bash "$HERE/collab-context-collect.sh" --role senior --no-github --no-files >/dev/null
test -s .dx/senior-context.md

jq -e \
  '.values.role == "senior" and .values.out == ".dx/senior-context.md"' \
  "$profile" >/dev/null

printf 'PASS: lead to senior uses role-specific default output\n'

bash "$HERE/collab-profile-clear.sh" context

bash "$HERE/collab-context-collect.sh" --role senior --no-github --no-files >/dev/null
bash "$HERE/collab-context-collect.sh" --role lead --no-github --no-files >/dev/null

jq -e \
  '.values.role == "lead" and .values.out == ".dx/lead-context.md"' \
  "$profile" >/dev/null

printf 'PASS: senior to lead uses role-specific default output\n'

bash "$HERE/collab-context-collect.sh" \
  --role lead \
  --out .dx/custom-lead.md \
  --no-github \
  --no-files >/dev/null

bash "$HERE/collab-context-collect.sh" \
  --role lead \
  --no-github \
  --no-files >/dev/null

jq -e \
  '.values.out == ".dx/custom-lead.md"' \
  "$profile" >/dev/null

printf 'PASS: same-role profile reload preserves explicit custom output\n'

bash "$HERE/collab-context-collect.sh" \
  --role senior \
  --no-github \
  --no-files >/dev/null

jq -e \
  '.values.out == ".dx/senior-context.md"' \
  "$profile" >/dev/null

printf 'PASS: role switch does not inherit remembered custom output\n'

jq -e \
  '.values.includes == [] and .values.excludes == [] and .values.consumerIncludes == []' \
  "$profile" >/dev/null

printf 'PASS: empty context collections persist as empty arrays\n'

python3 - <<'PY2'
import json
from pathlib import Path

path = Path('.dx/collab/profiles/context.json')
document = json.loads(path.read_text(encoding='utf-8'))
document['values']['includes'] = ['']
path.write_text(
    json.dumps(document) + '\n',
    encoding='utf-8',
)
PY2

chmod 600 "$profile" 2>/dev/null || true

! python3 "$HERE/collab-state.py" load context >/dev/null 2>&1

printf 'PASS: malformed empty context paths are rejected on reload\n'

! bash "$HERE/collab-context-collect.sh" \
  --no-github \
  --no-files >/dev/null 2>&1

printf 'PASS: role remains an explicit required command argument\n'
