#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
require_cmd git; root=$(repo_root); cd "$root"
include_diff=false; dx_output=''
paths=()
while (($#)); do case "$1" in --diff) include_diff=true;; --dx) shift; (($#)) || usage_error '--dx requires a path'; dx_output=$1;; -h|--help) echo 'Usage: repo-source-snapshot.sh [--diff] [--dx FILE] [PATH ...]'; exit 0;; -*) usage_error "unknown option: $1";; *) paths+=("$1");; esac; shift; done
((${#paths[@]})) || paths=(.)
mapfile -d '' selected < <(find "${paths[@]}" -type f ! -path '*/.git/*' ! -path '*/.dx/*' ! -path '*/bin/*' ! -path '*/obj/*' -print0 | sort -z)
if [[ -n "$dx_output" ]]; then
  { printf '%%%%DX v1.3\n'; for f in "${selected[@]}"; do rel=${f#./}; [[ "$f" == /* ]] && rel=${f#"$root"/}; printf '%%%%FILE path="%s" readonly="true"\n' "$rel"; cat -- "$f"; [[ -s "$f" && $(tail -c 1 -- "$f" | wc -l) -eq 0 ]] && printf '\n'; printf '%%%%ENDBLOCK\n'; done; printf '%%%%END\n'; } > "$dx_output"
  printf 'Snapshot written: %s\nFiles: %d\n' "$dx_output" "${#selected[@]}"; exit 0
fi
printf '=== GIT STATE ===\nRoot: %s\nBranch: %s\nHEAD: %s\nStatus:\n' "$root" "$(git branch --show-current)" "$(git rev-parse HEAD)"; git status --short
printf '\n=== FILE TREE ===\n'; printf '%s\n' "${selected[@]}"
for f in "${selected[@]}"; do printf '\n===== FILE: %s =====\n' "${f#./}"; cat -- "$f"; done
$include_diff && { printf '\n=== DIFF ===\n'; git diff --find-renames; }
