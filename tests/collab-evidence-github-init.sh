#!/usr/bin/env bash
set -Eeuo pipefail
REPO=ulfbou/mock-repo; BASE=test-base
verify_access(){ gh auth status >/dev/null;[[ $(gh repo view "$REPO" --json nameWithOwner --jq .nameWithOwner)=="$REPO" ]];[[ $(gh api "repos/$REPO" --jq .permissions.push)==true ]];gh api "repos/$REPO/git/ref/heads/$BASE" >/dev/null; }
verify_access;T=$(mktemp -d);trap 'rm -rf "$T"' EXIT;gh repo clone "$REPO" "$T/repo";cd "$T/repo";git fetch origin;git switch -C "$BASE" "origin/$BASE" 2>/dev/null||git switch --orphan "$BASE";git rm -rf . >/dev/null 2>&1||true;mkdir -p fixtures/selected;printf '# mock-repo\nPermanent Issue 10 fixture repository.\nDo not modify test-base.\n'>README.md;printf 'included\n'>fixtures/included.txt;printf 'alpha\n'>fixtures/selected/alpha.txt;printf 'beta\n'>fixtures/selected/beta.txt;python3 - <<'PY'
from pathlib import Path
Path('fixtures/oversized.txt').write_text('X'*300000+'\n');Path('fixtures/binary.bin').write_bytes(b'\0\1\2\3');Path('fixtures/non-utf8.bin').write_bytes(b'\xff\xfe\xfd')
PY
git add .;git diff --cached --quiet||git -c user.name=collab-fixture -c user.email=fixture@example.invalid commit -m 'Repair Issue 10 fixture baseline';git push --force-with-lease origin "$BASE"