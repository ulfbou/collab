#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
json=false; explicit_repo=''
while (($#)); do case "$1" in --json) json=true;; -h|--help) echo 'Usage: repo-state.sh [OWNER/REPO] [--json]'; exit 0;; -*) usage_error "unknown option: $1";; *) [[ -z "$explicit_repo" ]] || usage_error 'only one repository argument is allowed'; explicit_repo=$1;; esac; shift; done
require_cmd git; root=$(repo_root); cd "$root"
repo=$(origin_repo); [[ -z "$explicit_repo" || "$repo" == "$explicit_repo" ]] || die "origin is $repo, expected $explicit_repo"
branch=$(git branch --show-current); [[ -n "$branch" ]] || branch='(detached)'
default=$(default_branch); [[ -n "$default" ]] || die 'default branch cannot be determined'
head=$(git rev-parse HEAD); remote_ref="origin/$default"; remote_sha=$(git rev-parse "$remote_ref" 2>/dev/null || true)
ahead='unknown'; behind='unknown'; if [[ -n "$remote_sha" ]]; then read -r behind ahead < <(git rev-list --left-right --count "$remote_ref...HEAD"); fi
status=$(git status --porcelain=v1 --untracked-files=all); staged=$(git diff --cached --name-status); unstaged=$(git diff --name-status); untracked=$(git ls-files --others --exclude-standard)
pr=''; if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 && [[ "$branch" != '(detached)' ]]; then pr=$(gh pr list --repo "$repo" --head "$branch" --state open --json number,title,state,url 2>/dev/null || true); fi
if $json; then require_cmd jq; jq -n --arg repository "$repo" --arg root "$root" --arg branch "$branch" --arg defaultBranch "$default" --arg head "$head" --arg remoteSha "$remote_sha" --arg ahead "$ahead" --arg behind "$behind" --arg status "$status" --arg staged "$staged" --arg unstaged "$unstaged" --arg untracked "$untracked" --argjson pr "${pr:-[]}" '{repository:$repository,root:$root,branch:$branch,defaultBranch:$defaultBranch,head:$head,originDefaultSha:$remoteSha,ahead:$ahead,behind:$behind,clean:($status==""),status:$status,staged:$staged,unstaged:$unstaged,untracked:$untracked,currentBranchPullRequests:$pr}'
else
 printf 'Repository: %s\nRoot: %s\nOrigin: %s\nBranch: %s\nDefault branch: %s\nHEAD: %s\norigin/%s: %s\nAhead: %s\nBehind: %s\nWorking tree: %s\n' "$repo" "$root" "$(git remote get-url origin)" "$branch" "$default" "$head" "$default" "${remote_sha:-UNAVAILABLE}" "$ahead" "$behind" "$([[ -z "$status" ]] && echo CLEAN || echo DIRTY)"
 printf '\nStaged changes:\n%s\n\nUnstaged changes:\n%s\n\nUntracked files:\n%s\n\nCurrent branch PR:\n%s\n\nRecent commits:\n' "${staged:-none}" "${unstaged:-none}" "${untracked:-none}" "${pr:-unavailable or none}"; git log -5 --date=iso-strict --pretty='format:%h %ad %s'
fi
