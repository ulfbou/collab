#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
usage() {
  cat <<'USAGE'
Usage:
  collab-artifact-publish.sh --run-id RUN_ID --source FILE --stable FILE [--source FILE --stable FILE ...]

Purpose:
  Atomically publish immutable run artifacts to stable .dx paths after verifying
  that every source artifact and hash is recorded in the completed run record.
USAGE
}
run_id=''; sources=(); stable=()
while (($#)); do
  case "$1" in
    --run-id) shift; (($#)) || usage_error '--run-id requires a value'; run_id=$1 ;;
    --source) shift; (($#)) || usage_error '--source requires a path'; sources+=("$1") ;;
    --stable) shift; (($#)) || usage_error '--stable requires a path'; stable+=("$1") ;;
    -h|--help) usage; exit 0 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
  shift
done
[[ $run_id =~ ^[0-9]{8}T[0-9]{6}\.[0-9]{9}Z-[0-9]+-[0-9a-f]{8}$ ]] || usage_error 'invalid run ID'
((${#sources[@]} > 0 && ${#sources[@]} == ${#stable[@]})) || usage_error 'each --source requires one corresponding --stable'
require_cmd jq; require_cmd sha256sum; require_cmd python3
root=$(repo_root); cd "$root"; record="$root/.dx/collab/runs/$run_id/run.json"
[[ -f $record && ! -L $record ]] || die "run record not found or unsafe: $record"
jq -e --arg id "$run_id" '.schemaVersion == "1.0" and .runId == $id and .status == "success" and (.artifacts | type == "array")' "$record" >/dev/null || die 'only a valid successful run may publish stable artifacts'
temps=(); cleanup() { local x; for x in "${temps[@]}"; do rm -f -- "$x"; done; }; trap cleanup EXIT
for index in "${!sources[@]}"; do
  source_path=${sources[$index]}; stable_path=${stable[$index]}
  [[ -f $source_path && ! -L $source_path ]] || die "source artifact is missing or unsafe: $source_path"
  [[ $stable_path == .dx/* && $stable_path != .dx/collab/runs/* ]] || die "stable artifact must be below .dx and outside immutable run directories: $stable_path"
  expected=$(jq -r --arg path "$source_path" '.artifacts[] | select(.path == $path) | .sha256' "$record")
  [[ $expected =~ ^[0-9a-f]{64}$ ]] || die "source artifact is not recorded by the run: $source_path"
  actual=$(sha256sum "$source_path" | awk '{print $1}'); [[ $actual == "$expected" ]] || die "source artifact hash differs from run evidence: $source_path"
  mkdir -p "$(dirname "$stable_path")"
  tmp=$(mktemp "${stable_path}.tmp.XXXXXX"); temps+=("$tmp")
  python3 - "$source_path" "$tmp" <<'PY'
from pathlib import Path
import os, shutil, sys
source, target = map(Path, sys.argv[1:])
with source.open('rb') as src, target.open('wb') as dst:
    shutil.copyfileobj(src, dst)
    dst.flush()
    os.fsync(dst.fileno())
PY
done
for index in "${!stable[@]}"; do mv -f -- "${temps[$index]}" "${stable[$index]}"; temps[$index]=''; done
trap - EXIT
printf 'Published %d stable artifact(s) from run %s.\n' "${#stable[@]}" "$run_id"
for index in "${!stable[@]}"; do printf '%s <- %s\n' "${stable[$index]}" "${sources[$index]}"; done
