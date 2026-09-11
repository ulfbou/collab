#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cp "$HERE"/{collab-artifact-publish.sh,lib-common.sh,collab-state.py} "$T/"; chmod +x "$T/"*.sh "$T/collab-state.py"; cd "$T"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/test.git; echo base>tracked;git add tracked;git commit -qm init
mkdir -p .dx/source;printf 'one
'>.dx/source/a; started=$(date +%s%N);head=$(git rev-parse HEAD);id=$(python3 collab-state.py run-id);python3 collab-state.py record --run-id "$id" --tool test --status success --exit-status 0 --started "$started" --start-head "$head" --artifact .dx/source/a
record=.dx/collab/runs/$id/run.json;immutable=$(jq -r '.artifacts[0].immutablePath' "$record");[[ -f $immutable ]];rm .dx/source/a;bash collab-artifact-publish.sh --run-id "$id" --source .dx/source/a --stable .dx/a >/dev/null;[[ $(cat .dx/a) == one ]];echo 'PASS: cleanup-safe publication'
printf old>.dx/a;printf bad>"$immutable";! bash collab-artifact-publish.sh --run-id "$id" --source .dx/source/a --stable .dx/a >/dev/null 2>&1;[[ $(cat .dx/a) == old ]];echo 'PASS: failed verification preserves stable artifact'
printf failure>.dx/source/f;fid=$(python3 collab-state.py run-id);python3 collab-state.py record --run-id "$fid" --tool test --status failure --exit-status 7 --failure-phase phase --started "$started" --start-head "$head" --artifact .dx/source/f;rm .dx/source/f;bash collab-artifact-publish.sh --run-id "$fid" --source .dx/source/f --stable .dx/f >/dev/null;[[ $(cat .dx/f) == failure ]];echo 'PASS: failed-run publication'
if ln -s ../tracked .dx/link 2>/dev/null
then
  ! bash collab-artifact-publish.sh     --run-id "$fid"     --source .dx/source/f     --stable .dx/link     >/dev/null 2>&1
  echo 'PASS: symlink rejected'
else
  rm -f -- .dx/link
  echo 'SKIP: filesystem does not permit creating symbolic links'
fi

! bash collab-artifact-publish.sh   --run-id "$fid"   --source .dx/unrecorded   --stable .dx/x   >/dev/null 2>&1
echo 'PASS: unrecorded artifact rejected'
