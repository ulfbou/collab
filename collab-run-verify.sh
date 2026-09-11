#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
require_cmd jq; require_cmd sha256sum
(($# == 1)) || usage_error 'Usage: collab-run-verify.sh RUN_ID'; run_id=$1
[[ $run_id =~ ^[0-9]{8}T[0-9]{6}\.[0-9]{9}Z-[0-9]+-[0-9a-f]{8}$ ]] || usage_error 'invalid run ID'
root=$(repo_root); cd "$root"; record="$root/.dx/collab/runs/$run_id/run.json"; [[ -f $record && ! -L $record ]] || die "run record not found or unsafe: $record"
jq -e --arg id "$run_id" '.schemaVersion=="1.0" and .runId==$id and (.status=="success" or .status=="failure") and (.artifacts|type=="array")' "$record" >/dev/null || die 'run record failed schema validation'
bad=0
while IFS=$'\t' read -r logical path expected_size expected_hash; do [[ -f $path && ! -L $path ]] || { printf 'MISSING OR UNSAFE: %s\n' "$path" >&2; bad=1; continue; }; size=$(wc -c < "$path"|tr -d ' '); hash=$(sha256sum "$path"|awk '{print $1}'); [[ $size == "$expected_size" ]] || { printf 'SIZE MISMATCH: %s\n' "$path" >&2; bad=1; }; [[ $hash == "$expected_hash" ]] || { printf 'HASH MISMATCH: %s\n' "$path" >&2; bad=1; }; done < <(jq -r '.artifacts[]|[.path,.immutablePath,(.size|tostring),.sha256]|@tsv' "$record")
((bad == 0)) || die 'run artifact verification failed'; printf 'PASS: run %s and all recorded artifacts verified.\n' "$run_id"
