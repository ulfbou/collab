#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

require() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing command: $1" >&2; exit 1; }; }
require git
require gh
require jq

repo_url=$(git remote get-url origin)
repo=${repo_url%.git}
repo=${repo#git@github.com:}
repo=${repo#https://github.com/}
repo=${repo#http://github.com/}

TITLE=""
BODY_FILE=""
MILESTONE=""
JSON=false
ASSIGNEES=()
LABELS=()

while (($#)); do
  case "$1" in
    --title) shift; TITLE=${1:?} ;;
    --body-file) shift; BODY_FILE=${1:?} ;;
    --milestone) shift; MILESTONE=${1:?} ;;
    --label) shift; LABELS+=("$1") ;;
    --assignee) shift; ASSIGNEES+=("$1") ;;
    --json) JSON=true ;;
    *) echo "USAGE ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$TITLE" ]] || { echo "USAGE ERROR: --title required" >&2; exit 2; }
[[ -f "$BODY_FILE" ]] || { echo "USAGE ERROR: body file not found" >&2; exit 2; }

if [[ -n "$MILESTONE" ]]; then
  if ! gh api "repos/$repo/milestones?state=all" --jq '.[].title' | grep -Fxq "$MILESTONE"; then
    gh api -X POST "repos/$repo/milestones" -f title="$MILESTONE" >/dev/null
  fi
fi

for label in "${LABELS[@]}"; do
  if ! gh label list --repo "$repo" --limit 500 --json name --jq '.[].name' | grep -Fxq "$label"; then
    gh label create "$label" --repo "$repo" --color 5319e7 >/dev/null
  fi
done

existing=$(gh issue list --repo "$repo" --state all --search "$TITLE in:title" --json number,title,url)
issue=$(jq -r --arg t "$TITLE" '.[]|select(.title==$t)|.number' <<<"$existing" | head -n1)
url=$(jq -r --arg t "$TITLE" '.[]|select(.title==$t)|.url' <<<"$existing" | head -n1)
created=false

if [[ -z "$issue" ]]; then
  args=(issue create --repo "$repo" --title "$TITLE" --body-file "$BODY_FILE")
  [[ -n "$MILESTONE" ]] && args+=(--milestone "$MILESTONE")
  for l in "${LABELS[@]}"; do args+=(--label "$l"); done
  for a in "${ASSIGNEES[@]}"; do args+=(--assignee "$a"); done
  url=$(gh "${args[@]}")
  issue=$(gh issue view "$url" --json number --jq .number)
  created=true
fi

if $JSON; then
  jq -n --argjson issue "$issue" --arg url "$url" --argjson created "$created" '{issue:$issue,url:$url,created:$created}'
else
  echo "Issue #$issue"
  echo "$url"
fi
