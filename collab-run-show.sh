#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
require_cmd jq
run_id=''; json=false
while (($#)); do case "$1" in --json) json=true;; -h|--help) echo 'Usage: collab-run-show.sh [RUN_ID] [--json]'; exit 0;; -*) usage_error "unknown option: $1";; *) [[ -z $run_id ]] || usage_error 'only one run ID is allowed'; run_id=$1;; esac; shift; done
root=$(repo_root); cd "$root"; runs="$root/.dx/collab/runs"; [[ -d $runs ]] || die 'no collaboration runs exist'
if [[ -z $run_id ]]; then mapfile -t records < <(find "$runs" -mindepth 2 -maxdepth 2 -type f -name run.json -print | sort); ((${#records[@]})) || die 'no completed collaboration runs exist'; record=${records[-1]}; else [[ $run_id =~ ^[0-9]{8}T[0-9]{6}\.[0-9]{9}Z-[0-9]+-[0-9a-f]{8}$ ]] || usage_error 'invalid run ID'; record="$runs/$run_id/run.json"; fi
[[ -f $record && ! -L $record ]] || die "run record not found or unsafe: $record"
jq -e '.schemaVersion == "1.0" and (.runId|type=="string") and (.artifacts|type=="array")' "$record" >/dev/null || die 'run record failed schema validation'
if $json; then cat -- "$record"; else jq -r '"Run ID: \(.runId)\nTool: \(.tool) \(.toolVersion)\nStatus: \(.status)\nExit status: \(.exitStatus)\nRepository: \(.repository)\nBranch: \(.branch)\nStart HEAD: \(.startHead)\nFinal HEAD: \(.finalHead)\nElapsed: \(.elapsedMilliseconds) ms\nFailure phase: \(.failurePhase // "none")\nArtifacts:\n" + (.artifacts|map("- \(.path)  \(.sha256)  \(.size) bytes")|join("\n"))' "$record"; fi
