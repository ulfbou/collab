#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
(($#==1)) || usage_error 'Usage: work-start.sh BRANCH'; branch=$1; require_cmd git; root=$(repo_root); cd "$root"; default=$(default_branch); current=$(git branch --show-current)
phase 'PREFLIGHT'; clean_tree || die 'working tree is not clean'; [[ "$current" == "$default" ]] || die "current branch is $current, expected $default"; git fetch --prune origin
local_sha=$(git rev-parse "$default"); remote_sha=$(git rev-parse "origin/$default"); [[ "$local_sha" == "$remote_sha" ]] || die "$default differs from origin/$default"
! git show-ref --verify --quiet "refs/heads/$branch" || die "local branch already exists: $branch"; ! git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1 || die "remote branch already exists: $branch"
phase 'MUTATION'; git pull --ff-only origin "$default"; base=$(git rev-parse HEAD); git switch -c "$branch"
BRANCH=$branch; collab_profile_save session BRANCH; collab_record_run work-start success "$branch" >/dev/null
phase 'POSTCONDITION'; printf 'Repository: %s\nBase SHA: %s\nBranch: %s\nWorking tree: %s\n' "$(origin_repo)" "$base" "$(git branch --show-current)" "$([[ -z "$(git status --porcelain)" ]] && echo CLEAN || echo DIRTY)"