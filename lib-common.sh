#!/usr/bin/env bash
# Shared runtime for ai-human collaboration tools. Source from executables only.
set -euo pipefail

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf 'lib-common.sh is a library and must not be executed directly.\n' >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
EXIT_FAIL=1
EXIT_USAGE=2

die() { printf 'ERROR: %s\n' "$*" >&2; exit "$EXIT_FAIL"; }
usage_error() { printf 'USAGE ERROR: %s\n' "$*" >&2; exit "$EXIT_USAGE"; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
phase() { printf '\n=== %s ===\n' "$1"; }
repo_root() { git rev-parse --show-toplevel 2>/dev/null || die 'not inside a Git repository'; }
default_branch() {
  local ref
  ref=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)
  if [[ -n "$ref" ]]; then printf '%s\n' "${ref#origin/}"; return; fi
  git remote show origin 2>/dev/null | sed -n 's/^[[:space:]]*HEAD branch: //p' | head -n 1
}
origin_repo() {
  local url
  url=$(git remote get-url origin 2>/dev/null) || die 'origin remote is unavailable'
  url=${url%.git}; url=${url#git@github.com:}; url=${url#https://github.com/}; url=${url#http://github.com/}
  [[ "$url" == */* ]] || die "cannot derive GitHub nameWithOwner from origin: $url"
  printf '%s\n' "$url"
}
require_executed() {
  if [[ "${BASH_SOURCE[1]:-}" != "$0" ]]; then
    die 'this script must be executed, not sourced'
  fi
}
clean_tree() { [[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]]; }


COLLAB_STATE="$SCRIPT_DIR/collab-state.py"
collab_state() { require_cmd python3; [[ -x "$COLLAB_STATE" ]] || die "missing executable: $COLLAB_STATE"; python3 "$COLLAB_STATE" "$@"; }
collab_profile_json() { collab_state load "$1"; }
collab_profile_save_json() { (($#==2)) || die 'collab_profile_save_json requires profile and JSON'; collab_state save "$1" --json "$2"; }
collab_run_id() { collab_state run-id; }

# Compatibility API backed by non-executable, schema-validated JSON profiles.
collab_profile_load() {
  local kind=$1 j
  require_cmd jq
  j=$(collab_profile_json "$kind")
  case "$kind" in
    session)
      BRANCH=$(jq -r '.branch // empty' <<<"$j")
      ;;
    context)
      ROLE=$(jq -r '.role // empty' <<<"$j"); ISSUE=$(jq -r '.issue // empty' <<<"$j")
      EXPECTED_REPO=$(jq -r '.expectedRepo // empty' <<<"$j"); OUT=$(jq -r '.out // empty' <<<"$j")
      MAX_FILE_BYTES=$(jq -r '.maxFileBytes // 262144' <<<"$j"); RECENT_COMMITS=$(jq -r '.recentCommits // 20' <<<"$j"); RECENT_CLOSED=$(jq -r '.recentClosed // 20' <<<"$j")
      WITH_GITHUB=$(jq -r 'if .withGitHub == false then 0 else 1 end' <<<"$j"); WITH_FILES=$(jq -r 'if .withFiles == false then 0 else 1 end' <<<"$j")
      ALL_OPEN_ISSUE_BODIES=$(jq -r 'if .allOpenIssueBodies == true then 1 else 0 end' <<<"$j")
      DELIVERY_BRIEF=$(jq -r '.deliveryBrief // empty' <<<"$j"); CONSUMER_ROOT=$(jq -r '.consumerRoot // empty' <<<"$j")
      mapfile -t INCLUDES < <(jq -r '.includes[]?' <<<"$j"); mapfile -t EXCLUDES < <(jq -r '.excludes[]?' <<<"$j"); mapfile -t CONSUMER_INCLUDES < <(jq -r '.consumerIncludes[]?' <<<"$j")
      ;;
    delivery)
      ISSUE=$(jq -r '.issue // empty' <<<"$j"); BRANCH=$(jq -r '.branch // empty' <<<"$j"); TITLE=$(jq -r '.title // empty' <<<"$j"); CARRIER=$(jq -r '.carrier // empty' <<<"$j")
      PROVIDER_SOLUTION=$(jq -r '.providerSolution // empty' <<<"$j"); CONSUMER_ROOT=$(jq -r '.consumerRoot // empty' <<<"$j"); CONSUMER_SOLUTION=$(jq -r '.consumerSolution // empty' <<<"$j")
      TOOLS_DIR=$(jq -r '.toolsDir // "/f/scripts"' <<<"$j"); OUTPUT_PREFIX=$(jq -r '.outputPrefix // "delivery"' <<<"$j"); SKIP_APPLY=$(jq -r 'if .skipApply == true then 1 else 0 end' <<<"$j")
      mapfile -t ALLOWS < <(jq -r '.allows[]?' <<<"$j"); mapfile -t FOCUSED_TESTS < <(jq -r '.focusedTests[]?' <<<"$j"); mapfile -t AUDIT_SCOPES < <(jq -r '.auditScopes[]?' <<<"$j")
      ;;
    pr|delta) : ;;
    *) die "unknown collaboration profile: $kind" ;;
  esac
}

_json_array() {
  if (($# == 0)); then
    printf '[]'
  else
    printf '%s\n' "$@" | jq -Rsc 'split("\n")[:-1]'
  fi
}
_bool_json() { [[ $1 == 1 || $1 == true ]] && printf true || printf false; }

collab_profile_save() {
  local kind=$1
  require_cmd jq
  case "$kind" in
    session)
      collab_profile_save_json session "$(jq -cn --arg branch "${BRANCH:-}" '{branch:$branch}')"
      ;;
    context)
      collab_profile_save_json context "$(jq -cn \
        --arg role "$ROLE" --arg issue "$ISSUE" --arg expectedRepo "$EXPECTED_REPO" --arg out "$OUT" \
        --argjson maxFileBytes "$MAX_FILE_BYTES" --argjson recentCommits "$RECENT_COMMITS" --argjson recentClosed "$RECENT_CLOSED" \
        --argjson withGitHub "$(_bool_json "$WITH_GITHUB")" --argjson withFiles "$(_bool_json "$WITH_FILES")" --argjson allOpenIssueBodies "$(_bool_json "$ALL_OPEN_ISSUE_BODIES")" \
        --arg deliveryBrief "$DELIVERY_BRIEF" --arg consumerRoot "$CONSUMER_ROOT" \
        --argjson includes "$(_json_array "${INCLUDES[@]}")" --argjson excludes "$(_json_array "${EXCLUDES[@]}")" --argjson consumerIncludes "$(_json_array "${CONSUMER_INCLUDES[@]}")" \
        '{role:$role,issue:$issue,expectedRepo:$expectedRepo,out:$out,maxFileBytes:$maxFileBytes,recentCommits:$recentCommits,recentClosed:$recentClosed,withGitHub:$withGitHub,withFiles:$withFiles,allOpenIssueBodies:$allOpenIssueBodies,deliveryBrief:$deliveryBrief,consumerRoot:$consumerRoot,includes:$includes,excludes:$excludes,consumerIncludes:$consumerIncludes}')"
      ;;
    delivery)
      collab_profile_save_json delivery "$(jq -cn \
        --arg issue "$ISSUE" --arg branch "$BRANCH" --arg title "$TITLE" --arg carrier "$CARRIER" --arg providerSolution "$PROVIDER_SOLUTION" \
        --arg consumerRoot "$CONSUMER_ROOT" --arg consumerSolution "$CONSUMER_SOLUTION" --arg toolsDir "$TOOLS_DIR" --arg outputPrefix "$OUTPUT_PREFIX" \
        --argjson skipApply "$(_bool_json "$SKIP_APPLY")" --argjson allows "$(_json_array "${ALLOWS[@]}")" --argjson focusedTests "$(_json_array "${FOCUSED_TESTS[@]}")" --argjson auditScopes "$(_json_array "${AUDIT_SCOPES[@]}")" \
        '{issue:$issue,branch:$branch,title:$title,carrier:$carrier,providerSolution:$providerSolution,consumerRoot:$consumerRoot,consumerSolution:$consumerSolution,toolsDir:$toolsDir,outputPrefix:$outputPrefix,skipApply:$skipApply,allows:$allows,focusedTests:$focusedTests,auditScopes:$auditScopes}')"
      ;;
    pr)
      # Delivery prepares only the PR identity; preserve richer existing metadata.
      local old
      old=$(collab_profile_json pr)
      collab_profile_save_json pr "$(jq -cn --argjson old "$old" --arg issue "${ISSUE:-}" --arg title "${TITLE:-}" --arg branch "${BRANCH:-}" '$old + {issue:$issue,title:$title,branch:$branch}')"
      ;;
    *) die "unsupported collaboration profile save: $kind" ;;
  esac
}

collab_record_run() {
  local kind=$1 status=$2 started start_head run_id arg
  shift 2
  started=$(date +%s%N 2>/dev/null || printf '%s000000000' "$(date +%s)")
  start_head=$(git rev-parse HEAD)
  run_id=$(collab_run_id)
  local -a cmd=(record --run-id "$run_id" --tool "$kind" --status "$status" --exit-status 0 --started "$started" --start-head "$start_head")
  for arg in "$@"; do [[ -f $arg ]] && cmd+=(--artifact "$arg"); done
  collab_state "${cmd[@]}" >/dev/null
}
