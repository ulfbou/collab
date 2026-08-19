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
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf 'WARNING: %s\n' "$*" >&2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_value() {
  (($# >= 2)) || die "$1 requires a value"
}

is_uint() {
  [[ $1 =~ ^[0-9]+$ ]]
}

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

# Explicit command-line values override repository-local remembered values.
collab_profile_load context
PROFILE_ROLE=$ROLE
PROFILE_OUT=$OUT

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

((ROLE_EXPLICIT == 1)) || die '--role is required'
[[ $ROLE == lead || $ROLE == senior ]] || die '--role must be lead or senior'
[[ -z $ISSUE ]] || is_uint "$ISSUE" || die '--issue must be numeric'
is_uint "$MAX_FILE_BYTES" || die '--max-file-bytes must be a non-negative integer'
is_uint "$RECENT_COMMITS" || die '--recent-commits must be a non-negative integer'
is_uint "$RECENT_CLOSED" || die '--recent-closed must be a non-negative integer'

require_cmd git
require_cmd python3
require_cmd sha256sum

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die 'not inside a Git repository'
cd "$ROOT"

if ((OUT_EXPLICIT == 0)); then
  if [[ $ROLE != "$PROFILE_ROLE" || -z $PROFILE_OUT ]]; then
    OUT=".dx/${ROLE}-context.md"
  else
    OUT=$PROFILE_OUT
  fi
fi

if ((OUT_EXPLICIT == 0)) && [[ $OUT == .dx/lead-context.md || $OUT == .dx/senior-context.md ]]; then
  expected_default=".dx/${ROLE}-context.md"
  [[ $OUT == "$expected_default" ]] || die "context profile role/output mismatch: role $ROLE cannot use $OUT"
fi
mkdir -p "$(dirname "$OUT")"

# Atomic/Symlink Safety Block (Issue 10)
OUT_ABS=$(python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
if p.is_symlink():
    sys.exit(22)
print(p.resolve())
PY
) || die "unsafe output path: $OUT is a symlink"

TMP=$(mktemp "${OUT_ABS}.tmp.XXXXXX")
trap 'rm -f "$TMP"' EXIT

origin_url=$(git remote get-url origin 2>/dev/null || true)
repo_from_origin=$(python3 - "$origin_url" <<'PY'
import re, sys
url = sys.argv[1].strip()
url = re.sub(r'\.git$', '', url)
for prefix in ('git@github.com:', 'https://github.com/', 'http://github.com/', 'ssh://git@github.com/'):
    if url.startswith(prefix):
        url = url[len(prefix):]
        break
print(url if url.count('/') == 1 else '')
PY
)
REPO=${EXPECTED_REPO:-$repo_from_origin}

if [[ -n $EXPECTED_REPO && -n $repo_from_origin && $EXPECTED_REPO != "$repo_from_origin" ]]; then
  die "origin is $repo_from_origin, expected $EXPECTED_REPO"
fi

GITHUB_AVAILABLE=0
if ((WITH_GITHUB)); then
  require_cmd gh
  require_cmd jq
  [[ -n $REPO ]] || die 'cannot determine GitHub owner/repo; use --repo'
  if gh auth status >/dev/null 2>&1; then
    GITHUB_AVAILABLE=1
  else
    warn 'GitHub authentication unavailable; GitHub sections will record an error'
  fi
fi

fence_for_path() {
  case "$1" in
    *.sh|*.bash) printf 'bash' ;;
    *.cs) printf 'csharp' ;;
    *.csproj|*.props|*.targets|*.slnx|*.xml) printf 'xml' ;;
    *.json) printf 'json' ;;
    *.yml|*.yaml) printf 'yaml' ;;
    *.md) printf 'markdown' ;;
    *.py) printf 'python' ;;
    *.js) printf 'javascript' ;;
    *.ts) printf 'typescript' ;;
    *.html) printf 'html' ;;
    *.css) printf 'css' ;;
    *) printf 'text' ;;
  esac
}

path_is_excluded() {
  local path=$1 prefix
  for prefix in "${EXCLUDES[@]}"; do
    [[ $path == "$prefix" || $path == "$prefix/"* ]] && return 0
  done
  return 1
}

is_probably_text() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = p.read_bytes()[:8192]
if b'\x00' in data:
    raise SystemExit(1)
try:
    data.decode('utf-8')
except UnicodeDecodeError:
    raise SystemExit(1)
PY
}

collect_paths() {
  local root=$1
  shift
  local -a requested=("$@")
  local item rel
  if ((${#requested[@]} == 0)); then
    return 0
  fi
  (
    cd "$root"
    for item in "${requested[@]}"; do
      if [[ -f $item ]]; then
        git ls-files -z -- "$item"
      elif [[ -d $item ]]; then
        git ls-files -z -- "$item"
      else
        printf 'MISSING\t%s\0' "$item"
      fi
    done
  ) | python3 -c 'import sys
items = sys.stdin.buffer.read().split(b"\0")
seen = set()
for raw in items:
    if not raw:
        continue
    value = raw.decode("utf-8", "strict")
    seen.add(value)
# Deterministic Collection (Issue 10)
for value in sorted(seen):
    print(value)'
}

emit_file() {
  local display=$1 absolute=$2 size hash fence
  if [[ ! -f $absolute ]]; then
    printf -- '- Missing file: `%s`\n' "$display"
    return
  fi
  size=$(wc -c < "$absolute" | tr -d ' ')
  if ((size > MAX_FILE_BYTES)); then
    hash=$(sha256sum "$absolute" | awk '{print $1}')
    printf '### `%s`\n\n' "$display"
    printf -- '- Skipped: file exceeds `%s` bytes\n' "$MAX_FILE_BYTES"
    printf -- '- Size: `%s` bytes\n' "$size"
    printf -- '- SHA-256: `%s`\n\n' "$hash"
    return
  fi
  if ! is_probably_text "$absolute"; then
    hash=$(sha256sum "$absolute" | awk '{print $1}')
    printf '### `%s`\n\n' "$display"
    printf -- '- Skipped: binary or non-UTF-8 file\n'
    printf -- '- Size: `%s` bytes\n' "$size"
    printf -- '- SHA-256: `%s`\n\n' "$hash"
    return
  fi
  hash=$(sha256sum "$absolute" | awk '{print $1}')
  fence=$(fence_for_path "$display")
  printf '### `%s`\n\n' "$display"
  printf -- '- Size: `%s` bytes\n' "$size"
  printf -- '- SHA-256: `%s`\n\n' "$hash"
  printf '````%s\n' "$fence"
  cat -- "$absolute"
  if [[ -s $absolute && $(tail -c 1 -- "$absolute" | wc -l) -eq 0 ]]; then
    printf '\n'
  fi
  printf '````\n\n'
}

emit_json_section() {
  local heading=$1 sort_key=$2
  shift 2
  printf '## %s\n\n' "$heading"
  if ((GITHUB_AVAILABLE)); then
    printf '````json\n'
    if ! out=$("$@"); then
      printf '{"error":"GitHub query failed"}\n'
    else
      if [[ -n $sort_key ]]; then
        printf '%s\n' "$out" | jq "sort_by($sort_key)" || printf '%s\n' "$out"
      else
        printf '%s\n' "$out"
      fi
    fi
    printf '````\n\n'
  else
    printf '_GitHub data unavailable._\n\n'
  fi
}

{
  printf '# Collaboration Context\n\n'
  printf -- '- Role: `%s`\n' "$ROLE"
  printf -- '- Generated UTC: `%s`\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf -- '- Repository root: `%s`\n' "$ROOT"
  printf -- '- GitHub repository: `%s`\n' "${REPO:-unavailable}"
  printf -- '- Primary issue: `%s`\n' "${ISSUE:-not specified}"
  printf -- '- Format: `standalone Markdown evidence, not a DX carrier`\n\n'

  printf '## Operator Model\n\n'
  printf 'The user is the sole local repository operator and courier between the Lead Developer and Senior Developer conversations. This report is evidence only and cannot be applied to a working tree.\n\n'

  printf '## Repository State\n\n'
  printf '````text\n'
  printf 'Repository: %s\n' "${REPO:-unknown}"
  printf 'Origin: %s\n' "${origin_url:-unavailable}"
  printf 'Root: %s\n' "$ROOT"
  printf 'Branch: %s\n' "$(git branch --show-current)"
  printf 'HEAD: %s\n' "$(git rev-parse HEAD)"
  printf 'Default branch: %s\n' "$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
  printf 'Status:\n'
  git status --short --branch
  printf '\nRecent commits:\n'
  git log -n "$RECENT_COMMITS" --date=iso-strict --pretty='format:%H%x09%ad%x09%s'
  printf '\n````\n\n'

  printf '## Tracked Repository Tree\n\n'
  printf '````text\n'
  git ls-files | sort
  printf '````\n\n'

  if [[ -n $DELIVERY_BRIEF ]]; then
    printf '## Lead Developer Delivery Brief\n\n'
    if [[ -f $DELIVERY_BRIEF ]]; then
      printf '````markdown\n'
      cat -- "$DELIVERY_BRIEF"
      [[ ! -s $DELIVERY_BRIEF || $(tail -c 1 -- "$DELIVERY_BRIEF" | wc -l) -ne 0 ]] || printf '\n'
      printf '````\n\n'
    else
      printf '_Missing delivery brief: `%s`_\n\n' "$DELIVERY_BRIEF"
    fi
  fi

  if ((WITH_GITHUB)); then
    emit_json_section 'GitHub Repository Metadata' '' \
      gh repo view "$REPO" --json nameWithOwner,description,url,defaultBranchRef,isPrivate,visibility

    if [[ -n $ISSUE ]]; then
      emit_json_section "Primary Issue #$ISSUE" '' \
        gh issue view "$ISSUE" --repo "$REPO" \
          --json number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,closedAt,url
      emit_json_section "Primary Issue #$ISSUE Comments" '.id' \
        gh api --paginate "repos/$REPO/issues/$ISSUE/comments?per_page=100"
    fi

    if [[ $ROLE == lead ]]; then
      if ((ALL_OPEN_ISSUE_BODIES)); then
        emit_json_section 'Open Issues' '.number' \
          gh issue list --repo "$REPO" --state open --limit 100 \
            --json number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,url
      else
        emit_json_section 'Open Issues' '.number' \
          gh issue list --repo "$REPO" --state open --limit 100 \
            --json number,title,state,labels,milestone,assignees,author,createdAt,updatedAt,url
      fi
      emit_json_section 'Recently Closed Issues' '.number' \
        gh issue list --repo "$REPO" --state closed --limit "$RECENT_CLOSED" \
          --json number,title,state,labels,milestone,assignees,author,closedAt,url
      emit_json_section 'Open Pull Requests' '.number' \
        gh pr list --repo "$REPO" --state open --limit 100 \
          --json number,title,body,state,isDraft,baseRefName,headRefName,headRefOid,labels,milestone,assignees,author,mergeable,statusCheckRollup,createdAt,updatedAt,url
      emit_json_section 'Recently Merged Pull Requests' '.number' \
        gh pr list --repo "$REPO" --state merged --limit "$RECENT_CLOSED" \
          --json number,title,body,baseRefName,headRefName,headRefOid,mergeCommit,mergedAt,labels,milestone,author,url
      emit_json_section 'Labels' '.name' gh label list --repo "$REPO" --limit 100 --json name,color,description
      emit_json_section 'Milestones' '.title?' gh api --paginate "repos/$REPO/milestones?state=all&per_page=100"
    else
      emit_json_section 'Open Pull Requests' '.number' \
        gh pr list --repo "$REPO" --state open --limit 100 \
          --json number,title,state,isDraft,baseRefName,headRefName,headRefOid,labels,milestone,mergeable,statusCheckRollup,url
    fi
  fi

  if ((WITH_FILES)); then
    printf '## Selected Repository Files\n\n'
    if ((${#INCLUDES[@]} == 0)); then
      printf '_No `--include` paths were supplied._\n\n'
    else
      while IFS= read -r rel; do
        if [[ $rel == MISSING$'\t'* ]]; then
          printf -- '- Missing requested path: `%s`\n' "${rel#*$'\t'}"
          continue
        fi
        path_is_excluded "$rel" && continue
        emit_file "$rel" "$ROOT/$rel"
      done < <(collect_paths "$ROOT" "${INCLUDES[@]}")
    fi
  fi

  if [[ -n $CONSUMER_ROOT ]]; then
    printf '## Consumer Repository\n\n'
    consumer_abs=$(cd "$CONSUMER_ROOT" 2>/dev/null && pwd -P) || {
      printf '_Consumer root unavailable: `%s`_\n\n' "$CONSUMER_ROOT"
      consumer_abs=""
    }
    if [[ -n $consumer_abs ]]; then
      printf '````text\n'
      printf 'Root: %s\n' "$consumer_abs"
      printf 'Origin: %s\n' "$(git -C "$consumer_abs" remote get-url origin 2>/dev/null || true)"
      printf 'Branch: %s\n' "$(git -C "$consumer_abs" branch --show-current)"
      printf 'HEAD: %s\n' "$(git -C "$consumer_abs" rev-parse HEAD)"
      printf 'Status:\n'
      git -C "$consumer_abs" status --short --branch
      printf '````\n\n'
      printf '### Selected Consumer Files\n\n'
      if ((${#CONSUMER_INCLUDES[@]} == 0)); then
        printf '_No `--consumer-include` paths were supplied._\n\n'
      else
        while IFS= read -r rel; do
          if [[ $rel == MISSING$'\t'* ]]; then
            printf -- '- Missing requested consumer path: `%s`\n' "${rel#*$'\t'}"
            continue
          fi
          emit_file "consumer/$rel" "$consumer_abs/$rel"
        done < <(collect_paths "$consumer_abs" "${CONSUMER_INCLUDES[@]}")
      fi
    fi
  fi

  printf '## Collection Summary\n\n'
  printf -- '- GitHub requested: `%s`\n' "$([[ $WITH_GITHUB == 1 ]] && printf yes || printf no)"
  printf -- '- GitHub available: `%s`\n' "$([[ $GITHUB_AVAILABLE == 1 ]] && printf yes || printf no)"
  printf -- '- Complete file contents requested: `%s`\n' "$([[ $WITH_FILES == 1 ]] && printf yes || printf no)"
  printf -- '- Maximum included file size: `%s` bytes\n' "$MAX_FILE_BYTES"
} > "$TMP"

mv -- "$TMP" "$OUT_ABS"
trap - EXIT

collab_profile_save context ROLE ISSUE EXPECTED_REPO OUT MAX_FILE_BYTES RECENT_COMMITS RECENT_CLOSED WITH_GITHUB WITH_FILES ALL_OPEN_ISSUE_BODIES DELIVERY_BRIEF CONSUMER_ROOT INCLUDES EXCLUDES CONSUMER_INCLUDES
collab_record_run context success "$OUT_ABS" >/dev/null

hash=$(sha256sum "$OUT_ABS" | awk '{print $1}')
size=$(wc -c < "$OUT_ABS" | tr -d ' ')
printf 'Context written: %s\n' "$OUT_ABS"
printf 'Role: %s\n' "$ROLE"
printf 'Size: %s bytes\n' "$size"
printf 'SHA-256: %s\n' "$hash"