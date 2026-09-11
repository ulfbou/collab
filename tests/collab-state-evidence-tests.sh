#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P); TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-state.py" "$TMP/"; cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/evidence.git
printf 'artifact\n' > artifact.txt; git add artifact.txt; git commit -qm init; started=$(date +%s%N); head=$(git rev-parse HEAD); id=$(python3 collab-state.py run-id)
python3 collab-state.py record --run-id "$id" --tool test --status success --exit-status 0 --started "$started" --start-head "$head" --artifact artifact.txt
record=".dx/collab/runs/$id/run.json"; jq -e --arg id "$id" '.runId==$id and .status=="success" and .exitStatus==0 and (.artifacts|length)==1 and .startHead==.finalHead' "$record" >/dev/null; printf 'PASS: structured run record\n'
! python3 collab-state.py record --run-id "$id" --tool test --status success --exit-status 0 --started "$started" --start-head "$head" >/dev/null 2>&1; printf 'PASS: duplicate run ID rejected\n'
expected=$(sha256sum artifact.txt|awk '{print $1}'); [[ $(jq -r '.artifacts[0].sha256' "$record") == "$expected" ]]; printf 'PASS: artifact hash recorded\n'
immutable=$(jq -r '.artifacts[0].immutablePath' "$record"); [[ -f $immutable ]]; [[ $(sha256sum "$immutable"|awk '{print $1}') == "$expected" ]]; printf 'PASS: immutable artifact identity recorded
'


absolute_artifact=$(python3 - <<'PY2'
from pathlib import Path
print(Path("artifact.txt").resolve())
PY2
)

absolute_id=$(python3 collab-state.py run-id)

python3 collab-state.py record \
  --run-id "$absolute_id" \
  --tool test \
  --status success \
  --exit-status 0 \
  --started "$started" \
  --start-head "$head" \
  --artifact "$absolute_artifact"

absolute_record=".dx/collab/runs/$absolute_id/run.json"

[[ $(jq -r '.artifacts[0].path' "$absolute_record") == "artifact.txt" ]]
[[ $(jq -r '.artifacts[0].immutablePath' "$absolute_record") == \
   ".dx/collab/runs/$absolute_id/artifacts/000-artifact.txt" ]]

printf 'PASS: absolute artifact input records repository-relative identity\n'
