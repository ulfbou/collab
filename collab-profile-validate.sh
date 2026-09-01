#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
(($# <= 1)) || usage_error 'Usage: collab-profile-validate.sh [session|context|delivery|delta|pr]'
profiles=(session context delivery delta pr); (($# == 0)) || profiles=("$1")
for profile in "${profiles[@]}"; do case "$profile" in session|context|delivery|delta|pr);; *) usage_error "unknown profile: $profile";; esac; collab_state load "$profile" >/dev/null; printf 'PASS: %s profile is absent or valid for this repository.\n' "$profile"; done
