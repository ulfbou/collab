#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
require_cmd git; root=$(repo_root); cd "$root"; default=$(default_branch); branch=$(git branch --show-current)
phase 'PREFLIGHT'; [[ -n "$branch" && "$branch" != "$default" ]] || die "verification requires a non-default branch"; [[ -z "$(git ls-files -u)" ]] || die 'merge conflicts are present'
if find . -path '*/bin/*' -o -path '*/obj/*' | grep -q .; then tracked_build=$(git ls-files | grep -E '(^|/)(bin|obj)/' || true); [[ -z "$tracked_build" ]] || die "tracked build artifacts found:\n$tracked_build"; fi
phase 'CHANGE AUDIT'; "$SCRIPT_DIR/collab-git-change-audit.sh"
phase 'EXECUTABLE VERIFICATION'; "$SCRIPT_DIR/collab-repo-verify.sh"
phase 'RESULT'; printf 'Branch: %s\nHEAD: %s\nChanged files:\n' "$branch" "$(git rev-parse HEAD)"; git status --short; git diff --stat; git diff --cached --stat