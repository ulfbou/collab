#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ ${BASH_SOURCE[0]} == "$0" ]] || { printf 'ERROR: this script must be executed, not sourced\n' >&2; exit 1; }
exec python3 "$SCRIPT_DIR/collab-chat.py" accept "$@"