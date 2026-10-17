#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"&&pwd -P);source "$SCRIPT_DIR/lib-common.sh";require_executed
for k in session context delivery delta pr;do printf '\n===== %s =====\n' "$k";collab_state load "$k"|python3 -m json.tool;done