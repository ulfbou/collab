#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"

git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/ulfbou/mock-repo.git

# Ensure LF line endings to avoid accidental binary classification
printf 'selected content\n' | tr -d '\r' > selected.txt
printf 'excluded content\n' | tr -d '\r' > excluded.txt
printf 'delivery instructions\n' | tr -d '\r' > delivery-brief.md

python3 - <<'PY'
from pathlib import Path
Path("oversized.txt").write_text("X" * 100 + "\n", encoding="utf-8")
Path("binary.bin").write_bytes(b"\x00\x01\x02")
Path("non-utf8.bin").write_bytes(b"\xff\xfe\xfd")
PY

git add .
git commit -qm init
git branch -M main

mkdir -p .git/refs/remotes/origin
printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD

pass() {
  printf 'PASS: %s\n' "$1"
}

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

# Direct export must satisfy the published repository-state contract.
mkdir export

python3 "$HERE/collab-evidence.py" export-json \
  --root . \
  --out-dir export \
  --no-github

jq -e '
  has("relationships") and
  (.relationships | type == "object") and
  (.relationships.providers | type == "array") and
  (.relationships.consumers | type == "array")
' export/repository-state.json >/dev/null ||
  fail 'direct repository-state export omits relationships'

pass 'direct repository-state export contains relationships'

# The standalone report must preserve context-specific information and
# complete selected-file evidence.
# Increase max-file-bytes to 50 so selected.txt (17 bytes) is included,
# while oversized.txt (101 bytes) is still omitted.
bash "$HERE/collab-context-collect.sh" \
  --role senior \
  --issue 24 \
  --no-github \
  --include selected.txt \
  --include oversized.txt \
  --include binary.bin \
  --include non-utf8.bin \
  --include missing.txt \
  --exclude excluded.txt \
  --max-file-bytes 50 \
  --recent-commits 1 \
  --recent-closed 2 \
  --delivery-brief delivery-brief.md \
  --out .dx/context.md >/dev/null

context=.dx/context.md
test -s "$context" ||
  fail 'standalone context report was not created'

grep -Fq 'senior' "$context" ||
  fail 'standalone context omits role'

grep -Fq '24' "$context" ||
  fail 'standalone context omits primary issue'

grep -Fq 'delivery instructions' "$context" ||
  fail 'standalone context omits delivery brief'

grep -Fq 'selected.txt' "$context" ||
  fail 'standalone context omits selected path'

grep -Fq 'selected content' "$context" ||
  fail 'standalone context omits selected file content'

selected_size=$(wc -c < selected.txt | tr -d ' ')
selected_hash=$(sha256sum selected.txt | awk '{print $1}')

grep -Fq "$selected_size" "$context" ||
  fail 'standalone context omits selected file size'

grep -Fq "$selected_hash" "$context" ||
  fail 'standalone context omits selected file SHA-256'

grep -Fq 'oversized.txt' "$context" ||
  fail 'standalone context omits oversized path'

oversized_size=$(wc -c < oversized.txt | tr -d ' ')
oversized_hash=$(sha256sum oversized.txt | awk '{print $1}')

grep -Fq "$oversized_size" "$context" ||
  fail 'standalone context omits oversized file size'

grep -Fq "$oversized_hash" "$context" ||
  fail 'standalone context omits oversized file SHA-256'

grep -Fqi 'oversized' "$context" ||
  fail 'standalone context omits oversized reason'

binary_size=$(wc -c < binary.bin | tr -d ' ')
binary_hash=$(sha256sum binary.bin | awk '{print $1}')

grep -Fq 'binary.bin' "$context" ||
  fail 'standalone context omits binary path'

grep -Fq "$binary_size" "$context" ||
  fail 'standalone context omits binary size'

grep -Fq "$binary_hash" "$context" ||
  fail 'standalone context omits binary SHA-256'

grep -Fqi 'binary' "$context" ||
  fail 'standalone context omits binary reason'

non_utf8_size=$(wc -c < non-utf8.bin | tr -d ' ')
non_utf8_hash=$(sha256sum non-utf8.bin | awk '{print $1}')

grep -Fq 'non-utf8.bin' "$context" ||
  fail 'standalone context omits non-UTF-8 path'

grep -Fq "$non_utf8_size" "$context" ||
  fail 'standalone context omits non-UTF-8 size'

grep -Fq "$non_utf8_hash" "$context" ||
  fail 'standalone context omits non-UTF-8 SHA-256'

grep -Fqi 'non-utf8' "$context" ||
  fail 'standalone context omits non-UTF-8 reason'

grep -Fq 'missing.txt' "$context" ||
  fail 'standalone context omits missing requested path'

grep -Fqi 'missing' "$context" ||
  fail 'standalone context omits missing-path status'

if grep -Fq 'excluded content' "$context"; then
  fail 'excluded file content entered standalone context'
fi

pass 'standalone context preserves complete selected evidence'

# --no-files must suppress selected file content while preserving the path
# selection contract in the persisted profile.
bash "$HERE/collab-context-collect.sh" \
  --role lead \
  --no-github \
  --no-files \
  --include selected.txt \
  --out .dx/no-files.md >/dev/null

if grep -Fq 'selected content' .dx/no-files.md; then
  fail '--no-files did not suppress selected file content'
fi

jq -e '
  .values.role == "lead" and
  .values.withFiles == false
' .dx/collab/profiles/context.json >/dev/null ||
  fail '--no-files state was not preserved in the context profile'

pass '--no-files suppresses file content and persists state'

# Invalid numeric arguments must fail as usage errors rather than reaching
# Python with malformed values.
for option in \
  --max-file-bytes \
  --recent-commits \
  --recent-closed
do
  if bash "$HERE/collab-context-collect.sh" \
    --role lead \
    --no-github \
    "$option" invalid \
    --out ".dx/invalid-${option#--}.md" \
    >invalid.out 2>&1
  then
    fail "$option accepted a non-numeric value"
  fi
done

pass 'invalid numeric arguments are rejected'

# Required option values must not be consumed as empty or unrelated values.
for option in \
  --role \
  --issue \
  --repo \
  --out \
  --include \
  --exclude \
  --max-file-bytes \
  --recent-commits \
  --recent-closed \
  --delivery-brief \
  --consumer-root \
  --consumer-include
do
  if bash "$HERE/collab-context-collect.sh" \
    --role lead \
    --no-github \
    "$option" \
    >missing-value.out 2>&1
  then
    fail "$option accepted a missing value"
  fi
done

pass 'missing option values are rejected'

# Help and version remain explicit, successful command surfaces.
bash "$HERE/collab-context-collect.sh" --help >help.out
grep -Fq -- '--delivery-brief' help.out ||
  fail 'help omits --delivery-brief'
grep -Fq -- '--recent-closed' help.out ||
  fail 'help omits --recent-closed'
grep -Fq -- '--all-open-issue-bodies' help.out ||
  fail 'help omits --all-open-issue-bodies'
grep -Fq -- '--consumer-include' help.out ||
  fail 'help omits --consumer-include'

bash "$HERE/collab-context-collect.sh" --version >version.out
grep -Eq '^collab-context-collect\.sh [0-9]+\.[0-9]+\.[0-9]+$' \
  version.out ||
  fail 'version output is malformed'

pass 'help and version contracts are preserved'