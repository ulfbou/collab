#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
out=''; dry=false
while (($#)); do case "$1" in --out) shift; (($#))||usage_error '--out requires a path';out=$1;; --dry-run) dry=true;; -h|--help) echo 'Usage: collab-dx-delta-pack.sh [--out FILE] [--dry-run]';exit 0;; *) usage_error "unknown argument: $1";; esac;shift;done
require_cmd jq;require_cmd python3;root=$(repo_root);cd "$root"
remembered=$(collab_profile_json delta);out=${out:-$(jq -r '.outputFile // ".dx/proposed-delivery.dx.txt"'<<<"$remembered")}
if $dry; then printf 'Would pack current additions and modifications to: %s\n' "$out";exit 0;fi
python3 "$SCRIPT_DIR/collab-dx-pack.py" --out "$out" --from-git
"$SCRIPT_DIR/collab-dx-inspect.sh" "$out"
collab_profile_save_json delta "$(jq -cn --arg x "$out" '{outputFile:$x}')"