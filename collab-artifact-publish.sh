#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
run_id=''; sources=(); stable=()
while (($#)); do case "$1" in --run-id) shift; run_id=${1:?};; --source) shift; sources+=("${1:?}");; --stable) shift; stable+=("${1:?}");; -h|--help) echo 'Usage: collab-artifact-publish.sh --run-id ID --source LOGICAL --stable .dx/PATH [pairs...]'; exit 0;; *) usage_error "unknown argument: $1";; esac; shift; done
[[ $run_id =~ ^[0-9]{8}T[0-9]{6}\.[0-9]{9}Z-[0-9]+-[0-9a-f]{8}$ ]] || usage_error 'invalid run ID'
((${#sources[@]} && ${#sources[@]}==${#stable[@]})) || usage_error 'source/stable pairs required'
require_cmd jq; require_cmd sha256sum; require_cmd python3
root=$(repo_root); cd "$root"; record=".dx/collab/runs/$run_id/run.json"
[[ -f $record && ! -L $record ]] || die 'run record missing or unsafe'
jq -e --arg id "$run_id" '.schemaVersion=="1.0" and .runId==$id and (.status=="success" or .status=="failure") and (.artifacts|type=="array")' "$record" >/dev/null || die 'invalid completed run record'
temps=(); cleanup(){ local x; for x in "${temps[@]}"; do [[ -z $x ]] || rm -f -- "$x"; done; }; trap cleanup EXIT
for i in "${!sources[@]}"; do
 logical=${sources[$i]}; target=${stable[$i]}
 [[ $target == .dx/* && $target != .dx/collab/runs/* && $target != *'/../'* && ! -L $target ]] || die "unsafe stable path: $target"
 parent=$(dirname "$target"); [[ ! -L $parent ]] || die "unsafe stable parent: $parent"; mkdir -p "$parent"
 row=$(jq -er --arg p "$logical" '[.artifacts[]|select(.path==$p)]|if length==1 then .[0]|[.immutablePath,(.size|tostring),.sha256]|@tsv else error("not unique") end' "$record") || die "logical artifact not uniquely recorded: $logical"
 IFS=$'	' read -r rel expected_size expected_hash <<<"$row"
 [[ $rel == .dx/collab/runs/$run_id/artifacts/* && $expected_size =~ ^[0-9]+$ && $expected_hash =~ ^[0-9a-f]{64}$ ]] || die 'invalid immutable identity'
 immutable="$root/$rel"; [[ -f $immutable && ! -L $immutable ]] || die 'immutable artifact missing or unsafe'
 size=$(wc -c < "$immutable"|tr -d ' '); hash=$(sha256sum "$immutable"|awk '{print $1}'); [[ $size == "$expected_size" && $hash == "$expected_hash" ]] || die 'immutable identity mismatch'
 tmp=$(mktemp "${target}.tmp.XXXXXX"); temps+=("$tmp")
 python3 - "$immutable" "$tmp" <<'PY2'
from pathlib import Path
import os,shutil,sys
source,target=map(Path,sys.argv[1:])
with source.open('rb') as src,target.open('wb') as dst: shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
PY2
 size=$(wc -c < "$tmp"|tr -d ' '); hash=$(sha256sum "$tmp"|awk '{print $1}'); [[ $size == "$expected_size" && $hash == "$expected_hash" ]] || die 'temporary identity mismatch'
done
for i in "${!stable[@]}"; do mv -f -- "${temps[$i]}" "${stable[$i]}"; temps[$i]=''; done
trap - EXIT
printf 'Published %d stable artifact(s) from run %s.
' "${#stable[@]}" "$run_id"
