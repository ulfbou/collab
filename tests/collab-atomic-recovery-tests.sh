#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-state.py" "$TMP/"; cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/recovery.git; printf 'x\n' > x; git add x; git commit -qm init
python3 collab-state.py save session --json '{"branch":"test/old"}'; profile=.dx/collab/profiles/session.json; old_hash=$(sha256sum "$profile"|awk '{print $1}')
# A stale temporary file must neither replace nor invalidate the committed profile.
printf '{partial' > "${profile}.tmp.interrupted"; [[ $(python3 collab-state.py load session | python3 -c 'import json,sys;print(json.load(sys.stdin)["branch"])') == test/old ]]; [[ $(sha256sum "$profile"|awk '{print $1}') == "$old_hash" ]]
python3 collab-state.py save session --json '{"branch":"test/new"}'; [[ $(python3 collab-state.py load session | python3 -c 'import json,sys;print(json.load(sys.stdin)["branch"])') == test/new ]]; printf 'PASS: stale temporary file does not corrupt atomic profile replacement\n'
# An existing immutable run directory causes failure without modifying its final record.
id=$(python3 collab-state.py run-id); mkdir -p ".dx/collab/runs/$id"; printf 'sentinel\n' > ".dx/collab/runs/$id/run.json"; before=$(sha256sum ".dx/collab/runs/$id/run.json"|awk '{print $1}'); started=$(date +%s%N); head=$(git rev-parse HEAD)
! python3 collab-state.py record --run-id "$id" --tool test --status success --exit-status 0 --started "$started" --start-head "$head" >/dev/null 2>&1; [[ $(sha256sum ".dx/collab/runs/$id/run.json"|awk '{print $1}') == "$before" ]]; printf 'PASS: existing run record is never overwritten\n'