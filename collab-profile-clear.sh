#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"&&pwd -P);source "$SCRIPT_DIR/lib-common.sh";require_executed
(($#<=1))||usage_error 'Usage: collab-profile-clear.sh [session|context|delivery|delta|pr]';collab_state clear "$@"