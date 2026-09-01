#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"
require_executed

require_cmd git
root=$(repo_root)
cd "$root"
allows=()

while (($#)); do
  case "$1" in
    --allow)
      shift
      (($#)) || usage_error '--allow requires a path'
      allows+=("${1%/}/")
      ;;
    -h|--help)
      echo 'Usage: git-change-audit.sh [--allow PATH]...'
      exit 0
      ;;
    *)
      usage_error "unknown argument: $1"
      ;;
  esac
  shift
done

phase 'CHANGE SUMMARY'
git status --short
git diff --stat
git diff --cached --stat

phase 'NAME STATUS AND RENAMES'
git diff --find-renames --name-status
git diff --cached --find-renames --name-status

phase 'NUMSTAT'
git diff --numstat
git diff --cached --numstat

bad=0
while IFS=$'\t' read -r status path rest; do
  [[ -n "$status" ]] || continue
  check_path=${rest:-$path}
  check_path=${check_path#* => }
  check_path=${check_path%\}}

  if ((${#allows[@]})); then
    ok=0
    for allowed_path in "${allows[@]}"; do
      [[ "$check_path/" == "$allowed_path"* ]] && ok=1
    done

    ((ok)) || {
      printf 'OUT OF SCOPE: %s\n' "$check_path" >&2
      bad=1
    }
  fi
done < <({ git diff --name-status; git diff --cached --name-status; } | sort -u)

phase 'TRUNCATION HEURISTIC'
while IFS=$'\t' read -r additions deletions path; do
  [[ "$additions" =~ ^[0-9]+$ && "$deletions" =~ ^[0-9]+$ ]] || continue

  if ((deletions >= 100 && additions * 4 < deletions)); then
    printf 'SUSPICIOUS REDUCTION: %s additions=%s deletions=%s\n' \
      "$path" "$additions" "$deletions" >&2
    bad=1
  fi
done < <({ git diff --numstat; git diff --cached --numstat; } | sort -u)

phase 'DIFF CHECK'
git diff --check
git diff --cached --check

((bad == 0)) || die 'change audit found suspicious or out-of-scope changes'
printf 'Change audit completed without flagged conditions.\n'
