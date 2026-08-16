#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"; cp "$HERE/collab-dx-delta-pack.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$HERE/collab-dx-pack.py" "$TMP/"
cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/dry-run.git; printf 'base\n' > tracked; git add tracked; git commit -qm init; git remote set-head origin -a >/dev/null 2>&1 || true
before=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
PATH="$TMP/bin:$PATH" bash ./collab-dx-delta-pack.sh --out .dx/would-write.dx.txt --dry-run >/dev/null
after=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
[[ $before == "$after" ]]; [[ ! -e .dx/would-write.dx.txt && ! -e .dx/collab ]]; printf 'PASS: delta dry-run performs no writes\n'