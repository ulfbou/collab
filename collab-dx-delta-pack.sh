#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"
require_executed
OUTPUT_FILE=''
DRY_RUN=false
INCLUDE_NON_UTF8=false
OMIT_NON_UTF8=false
INCLUDES=()
EXCLUDES=()
while (($#)); do
  case "$1" in
    --out) shift; (($#)) || usage_error '--out requires a path'; OUTPUT_FILE=$1 ;;
    --include) shift; (($#)) || usage_error '--include requires a pattern'; INCLUDES+=("$1") ;;
    --exclude) shift; (($#)) || usage_error '--exclude requires a pattern'; EXCLUDES+=("$1") ;;
    --include-non-utf8) INCLUDE_NON_UTF8=true ;;
    --omit-non-utf8) OMIT_NON_UTF8=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) printf '%s\n' 'Usage: collab-dx-delta-pack.sh [--out FILE] [--include PATTERN] [--exclude PATTERN] [--include-non-utf8|--omit-non-utf8] [--dry-run]'; exit 0 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
  shift
done
$INCLUDE_NON_UTF8 && $OMIT_NON_UTF8 && usage_error '--include-non-utf8 and --omit-non-utf8 are mutually exclusive'
require_cmd git
require_cmd python3
root=$(repo_root)
cd "$root"
if $DRY_RUN; then
  printf 'DRY RUN: would package current Git changes with the canonical DX engine.\n'
  exit 0
fi
collab_profile_load delta
OUTPUT_FILE=${OUTPUT_FILE:-${OUTPUT_FILE:-.dx/proposed-delivery.dx.txt}}
mkdir -p "$(dirname "$OUTPUT_FILE")"
args=(pack --out "$OUTPUT_FILE" --root "$root" --from-git)
for pattern in "${INCLUDES[@]}"; do args+=(--include "$pattern"); done
for pattern in "${EXCLUDES[@]}"; do args+=(--exclude "$pattern"); done
$INCLUDE_NON_UTF8 && args+=(--include-non-utf8)
$OMIT_NON_UTF8 && args+=(--omit-non-utf8)
python3 "$SCRIPT_DIR/dx.py" "${args[@]}"
"$SCRIPT_DIR/collab-dx-inspect.sh" "$OUTPUT_FILE"
collab_profile_save delta OUTPUT_FILE
collab_record_run delta-pack success "$OUTPUT_FILE" >/dev/null
printf 'Carrier written: %s\n' "$OUTPUT_FILE"
