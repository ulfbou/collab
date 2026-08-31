#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"
require_executed
(($# == 1)) || usage_error 'Usage: collab-dx-apply-checked.sh CARRIER'
carrier=$1
[[ -f "$carrier" ]] || die "carrier not found: $carrier"
require_cmd git
require_cmd python3
root=$(repo_root)
cd "$root"
default=$(default_branch)
branch=$(git branch --show-current)
phase 'PREFLIGHT'
[[ -n "$branch" ]] || die 'detached HEAD is not allowed'
[[ "$branch" != "$default" ]] || die "refusing to mutate default branch: $default"
before=$(mktemp)
trap 'rm -f "$before"' EXIT
git status --porcelain=v1 --untracked-files=all > "$before"
printf 'Branch: %s\nHEAD: %s\n' "$branch" "$(git rev-parse HEAD)"
phase 'VERIFICATION'
"$SCRIPT_DIR/collab-dx-inspect.sh" "$carrier"
readonly=$("$SCRIPT_DIR/collab-dx-inspect.sh" "$carrier" --readonly)
[[ -z "$readonly" ]] || die "carrier targets readonly files:\n$readonly"
phase 'MUTATION'
python3 "$SCRIPT_DIR/dx.py" apply "$carrier" "$root" --force
phase 'POSTCONDITION'
git status --short
git diff --check
git diff --stat
git diff --find-renames --name-status
"$SCRIPT_DIR/collab-git-change-audit.sh"