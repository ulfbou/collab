#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-dx-pack.py" "$HERE/dx.py" "$TMP/"; cd "$TMP"
cp -R "$HERE/collab" "$TMP/"
pass(){ printf 'PASS: %s\n' "$1"; }
printf '\357\273\277text\n' > bom.txt; ! python3 collab-dx-pack.py --out x.dx --path bom.txt >/dev/null 2>&1; pass bom-rejected
printf 'line one\nline two\n' > lf.txt; python3 collab-dx-pack.py --out lf.dx --path lf.txt >/dev/null; grep -q '^    line one$' lf.dx; grep -q '^    line two$' lf.dx; pass canonical-lf-emitted
: > empty.txt; python3 collab-dx-pack.py --out empty.dx --path empty.txt >/dev/null; grep -q '^%%FILE path="empty.txt"$' empty.dx; pass empty-file-supported
printf 'delete me\n' > deleted.txt; rm deleted.txt; ! python3 collab-dx-pack.py --out deleted.dx --path deleted.txt >/dev/null 2>&1; pass deletion-rejected
printf 'quote\n' > 'bad"name'; ! python3 collab-dx-pack.py --out bad.dx --path 'bad"name' >/dev/null 2>&1; pass unrepresentable-path-rejected
mkdir repo; cd repo; git init -q; git config user.name Test; git config user.email test@example.invalid; printf 'base\n' > gone.txt; git add gone.txt; git commit -qm init; rm gone.txt; ! python3 ../collab-dx-pack.py --out gone.dx --from-git >/dev/null 2>&1; pass git-deletion-fails-closed
