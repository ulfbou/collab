#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-artifact-publish.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$TMP/"
chmod +x "$TMP/"*.sh "$TMP/collab-state.py"
cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/publication.git
printf 'base\n' > tracked; git add tracked; git commit -qm init
mkdir -p .dx/collab/source; printf 'version one\n' > .dx/collab/source/report.txt
started=$(date +%s%N); head=$(git rev-parse HEAD); run_id=$(python3 collab-state.py run-id)
python3 collab-state.py record --run-id "$run_id" --tool delivery --status success --exit-status 0 --started "$started" --start-head "$head" --artifact .dx/collab/source/report.txt
bash ./collab-artifact-publish.sh --run-id "$run_id" --source .dx/collab/source/report.txt --stable .dx/delivery-report.txt >/dev/null
cmp -s .dx/collab/source/report.txt .dx/delivery-report.txt; printf 'PASS: verified artifact atomically published\n'
printf 'tampered\n' > .dx/collab/source/report.txt
! bash ./collab-artifact-publish.sh --run-id "$run_id" --source .dx/collab/source/report.txt --stable .dx/delivery-report.txt >/dev/null 2>&1
[[ $(cat .dx/delivery-report.txt) == 'version one' ]]; printf 'PASS: tampered source rejected without replacing stable artifact\n'
started=$(date +%s%N); failed_id=$(python3 collab-state.py run-id)
python3 collab-state.py record --run-id "$failed_id" --tool delivery --status failure --exit-status 1 --started "$started" --start-head "$head"
! bash ./collab-artifact-publish.sh --run-id "$failed_id" --source .dx/collab/source/report.txt --stable .dx/failure.txt >/dev/null 2>&1; [[ ! -e .dx/failure.txt ]]; printf 'PASS: failed runs cannot publish stable artifacts\n'