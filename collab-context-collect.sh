#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=${0##*/}
VERSION="1.1.0"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"
require_executed

usage() {
  cat <<'USAGE'
Usage:
  collab-context-collect.sh --role lead|senior [options]

Purpose:
  Produce one standalone Markdown context report for a Lead Developer or Senior
  Developer conversation. The report is not a DX carrier and cannot be applied.

Required:
  --role ROLE                 lead or senior

Common options:
  --issue NUMBER              Primary issue to include in full
  --repo OWNER/REPO           Expected GitHub repository; defaults to origin
  --out FILE                  Output file; defaults to .dx/<role>-context.md
  --include PATH              Include complete tracked text files under PATH
                              Repeat for multiple paths
  --exclude PATH              Exclude repository-relative path prefix
                              Repeat for multiple paths
  --max-file-bytes NUMBER     Skip larger files; default 262144
  --recent-commits NUMBER     Recent commits to include; default 20
  --recent-closed NUMBER      Recent closed issues and merged PRs; default 20
  --no-github                 Skip GitHub collection
  --no-files                  Skip complete file-content collection

Senior-specific options:
  --delivery-brief FILE       Include the complete Lead delivery request
  --consumer-root PATH        Include consumer repository state and selected files
  --consumer-include PATH     Consumer-relative path to include; repeatable

Lead-specific options:
  --all-open-issue-bodies     Include full bodies for every open issue
                              By default, only the primary issue has a full body

Other:
  -h, --help                  Show help
  --version                   Show version

Examples:
  collab-context-collect.sh \
    --role lead \
    --issue 10 \
    --include docs \
    --include Verdant.slnx \
    --out .dx/lead-context.md

  collab-context-collect.sh \
    --role senior \
    --issue 10 \
    --delivery-brief .dx/issue-10-delivery-brief.md \
    --include Verdant.slnx \
    --include Directory.Build.props \
    --include src/Verdant.Core \
    --include src/Verdant.Replay \
    --include tests/Verdant.Core.Tests \
    --include tests/Verdant.ConformanceFixtures \
    --consumer-root ../moldfirstbloom \
    --consumer-include Mold.slnx \
    --consumer-include src/Mold.Engine \
    --consumer-include tests/Mold.Engine.Tests \
    --out .dx/senior-context.md
USAGE
}

# No redefinition of die/usage_error – use the ones from lib-common.sh.

require_value() {
  (($# >= 2)) || usage_error "$1 requires a value"
  # Reject a following argument that looks like an option (except for negative numbers? but we only accept non-negative)
  if [[ $2 == --* ]]; then
    usage_error "$1 requires a value, got option: $2"
  fi
}

is_uint() {
  [[ $1 =~ ^[0-9]+$ ]]
}

# Defaults
ROLE=""
ISSUE=""
EXPECTED_REPO=""
OUT=""
ROLE_EXPLICIT=0
OUT_EXPLICIT=0
MAX_FILE_BYTES=262144
RECENT_COMMITS=20
RECENT_CLOSED=20
WITH_GITHUB=1
WITH_FILES=1
ALL_OPEN_ISSUE_BODIES=0
DELIVERY_BRIEF=""
CONSUMER_ROOT=""
INCLUDES=()
EXCLUDES=()
CONSUMER_INCLUDES=()

# Load profile and capture remembered values
collab_profile_load context
PROFILE_ROLE=$ROLE
PROFILE_OUT=$OUT

# Parse command line
while (($#)); do
  case "$1" in
    --role) require_value "$@"; ROLE=$2; ROLE_EXPLICIT=1; shift 2 ;;
    --issue) require_value "$@"; ISSUE=$2; shift 2 ;;
    --repo) require_value "$@"; EXPECTED_REPO=$2; shift 2 ;;
    --out) require_value "$@"; OUT=$2; OUT_EXPLICIT=1; shift 2 ;;
    --include) require_value "$@"; INCLUDES+=("$2"); shift 2 ;;
    --exclude) require_value "$@"; EXCLUDES+=("${2%/}"); shift 2 ;;
    --max-file-bytes) require_value "$@"; MAX_FILE_BYTES=$2; shift 2 ;;
    --recent-commits) require_value "$@"; RECENT_COMMITS=$2; shift 2 ;;
    --recent-closed) require_value "$@"; RECENT_CLOSED=$2; shift 2 ;;
    --no-github) WITH_GITHUB=0; shift ;;
    --no-files) WITH_FILES=0; shift ;;
    --all-open-issue-bodies) ALL_OPEN_ISSUE_BODIES=1; shift ;;
    --delivery-brief) require_value "$@"; DELIVERY_BRIEF=$2; shift 2 ;;
    --consumer-root) require_value "$@"; CONSUMER_ROOT=$2; shift 2 ;;
    --consumer-include) require_value "$@"; CONSUMER_INCLUDES+=("$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --version) printf '%s %s\n' "$PROGRAM" "$VERSION"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

((ROLE_EXPLICIT == 1)) || usage_error '--role is required'
[[ $ROLE == lead || $ROLE == senior ]] || usage_error '--role must be lead or senior'
[[ -z $ISSUE ]] || is_uint "$ISSUE" || usage_error '--issue must be numeric'
is_uint "$MAX_FILE_BYTES" || usage_error '--max-file-bytes must be a non-negative integer'
is_uint "$RECENT_COMMITS" || usage_error '--recent-commits must be a non-negative integer'
is_uint "$RECENT_CLOSED" || usage_error '--recent-closed must be a non-negative integer'

# Ensure we are in a git repository
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die 'not inside a Git repository'
cd "$ROOT"

# Determine output path
if ((OUT_EXPLICIT == 0)); then
  if [[ $ROLE != "$PROFILE_ROLE" || -z $PROFILE_OUT ]]; then
    OUT=".dx/${ROLE}-context.md"
  else
    OUT=$PROFILE_OUT
  fi
fi

# Build arguments for python render-context
python_args=("$SCRIPT_DIR/collab-evidence.py" "render-context")
python_args+=("--root" "$ROOT")
python_args+=("--role" "$ROLE")
[[ -n "$ISSUE" ]] && python_args+=("--issue" "$ISSUE")
[[ -n "$EXPECTED_REPO" ]] && python_args+=("--repo" "$EXPECTED_REPO")
# Pass the original OUT path (not resolved) – Python will resolve and check symlink
python_args+=("--out" "$OUT")
[[ -n "$DELIVERY_BRIEF" ]] && python_args+=("--delivery-brief" "$DELIVERY_BRIEF")
[[ "$ALL_OPEN_ISSUE_BODIES" -eq 1 ]] && python_args+=("--all-open-issue-bodies")
python_args+=("--recent-closed" "$RECENT_CLOSED")
python_args+=("--max-bytes" "$MAX_FILE_BYTES")
python_args+=("--recent-commits" "$RECENT_COMMITS")
[[ "$WITH_GITHUB" -eq 0 ]] && python_args+=("--no-github")
[[ "$WITH_FILES" -eq 0 ]] && python_args+=("--no-files")
for inc in "${INCLUDES[@]}"; do
  python_args+=("--include" "$inc")
done
for exc in "${EXCLUDES[@]}"; do
  python_args+=("--exclude" "$exc")
done
[[ -n "$CONSUMER_ROOT" ]] && python_args+=("--consumer-root" "$CONSUMER_ROOT")
for cin in "${CONSUMER_INCLUDES[@]}"; do
  python_args+=("--consumer-include" "$cin")
done

# Execute the Python renderer (it performs atomic write and symlink checks)
if ! python3 "${python_args[@]}"; then
  die "Python render-context failed"
fi

# Determine absolute path for run record and summary
OUT_ABS=$(python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)

# Save the context profile with the final values (OUT is the original path)
collab_profile_save context ROLE ISSUE EXPECTED_REPO OUT MAX_FILE_BYTES RECENT_COMMITS RECENT_CLOSED WITH_GITHUB WITH_FILES ALL_OPEN_ISSUE_BODIES DELIVERY_BRIEF CONSUMER_ROOT INCLUDES EXCLUDES CONSUMER_INCLUDES

# Record the run with the absolute artifact path
collab_record_run context success "$OUT_ABS" >/dev/null

# Output summary
hash=$(sha256sum "$OUT_ABS" | awk '{print $1}')
size=$(wc -c < "$OUT_ABS" | tr -d ' ')
printf 'Context written: %s\n' "$OUT_ABS"
printf 'Role: %s\n' "$ROLE"
printf 'Size: %s bytes\n' "$size"
printf 'SHA-256: %s\n' "$hash"