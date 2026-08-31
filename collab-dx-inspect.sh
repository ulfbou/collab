#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
(($# >= 1)) || { printf 'Usage: collab-dx-inspect.sh CARRIER [--list|--hashes|--readonly|--file PATH|--compare-root ROOT]\n' >&2; exit 2; }
carrier=$1
shift
exec python3 "$SCRIPT_DIR/dx.py" inspect "$carrier" "$@"