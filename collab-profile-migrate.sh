#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
(($# == 0)) || usage_error 'Usage: collab-profile-migrate.sh'
root=$(repo_root); cd "$root"; legacy="$root/.dx/collab"; mapfile -t files < <(find "$legacy" -maxdepth 1 -type f -name '*.env' -print 2>/dev/null | sort)
if ((${#files[@]} == 0)); then printf 'No legacy executable profile files found.\n'; exit 0; fi
printf 'Legacy executable profiles were detected and were not loaded:\n'; printf -- '- %s\n' "${files[@]}"; printf '\nRun the normal commands once with explicit arguments to create validated JSON profiles. Remove legacy files manually only after review.\n'; exit 3
