#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=$(basename "$0")
VERSION="1.1.0"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"
require_executed

usage() {
  cat <<'USAGE'
Usage:
  collab-delivery-run.sh \
    --issue NUMBER \
    --branch BRANCH \
    --title TITLE \
    --carrier PATH \
    --provider-solution PATH \
    --consumer-root PATH \
    --consumer-solution PATH \
    --allow PATH [--allow PATH ...] \
    [--focused-test PROJECT ...] \
    [--audit-scope PATH ...] \
    [--tools-dir PATH] \
    [--output-prefix NAME] \
    [--skip-apply]

Purpose:
  Runs the approved bounded-delivery verification workflow, stops at the first
  error, preserves correction evidence, creates a final writable DX v1.3.1
  carrier from the actual changed files, and prints at most three files to
  upload for assessment.

Important:
  - Run from the repository root on the already-created non-default branch.
  - The initial carrier must contain the complete intended delivery.
  - For a corrected working tree, use --skip-apply and the script will package
    the actual staged/unstaged changed files after verification.
  - The script does not commit, push, create a PR, merge, or start another PR.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_value() {
  (($# >= 2)) || die "$1 requires a value"
}

ISSUE=""
BRANCH=""
TITLE=""
CARRIER=""
PROVIDER_SOLUTION=""
CONSUMER_ROOT=""
CONSUMER_SOLUTION=""
TOOLS_DIR="/f/scripts"
OUTPUT_PREFIX="delivery"
SKIP_APPLY=0
ALLOWS=()
FOCUSED_TESTS=()
AUDIT_SCOPES=()

collab_profile_load session
collab_profile_load delivery

while (($#)); do
  case "$1" in
    --issue) require_value "$@"; ISSUE=$2; shift 2 ;;
    --branch) require_value "$@"; BRANCH=$2; shift 2 ;;
    --title) require_value "$@"; TITLE=$2; shift 2 ;;
    --carrier) require_value "$@"; CARRIER=$2; shift 2 ;;
    --provider-solution) require_value "$@"; PROVIDER_SOLUTION=$2; shift 2 ;;
    --consumer-root) require_value "$@"; CONSUMER_ROOT=$2; shift 2 ;;
    --consumer-solution) require_value "$@"; CONSUMER_SOLUTION=$2; shift 2 ;;
    --allow) require_value "$@"; ALLOWS+=("$2"); shift 2 ;;
    --focused-test) require_value "$@"; FOCUSED_TESTS+=("$2"); shift 2 ;;
    --audit-scope) require_value "$@"; AUDIT_SCOPES+=("$2"); shift 2 ;;
    --tools-dir) require_value "$@"; TOOLS_DIR=$2; shift 2 ;;
    --output-prefix) require_value "$@"; OUTPUT_PREFIX=$2; shift 2 ;;
    --skip-apply) SKIP_APPLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --version) printf '%s %s\n' "$PROGRAM" "$VERSION"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$ISSUE" ]] || die '--issue is required'
[[ "$ISSUE" =~ ^[0-9]+$ ]] || die '--issue must be numeric'
[[ -n "$BRANCH" ]] || die '--branch is required'
[[ -n "$TITLE" ]] || die '--title is required'
[[ -n "$CARRIER" ]] || die '--carrier is required'
[[ -n "$PROVIDER_SOLUTION" ]] || die '--provider-solution is required'
[[ -n "$CONSUMER_ROOT" ]] || die '--consumer-root is required'
[[ -n "$CONSUMER_SOLUTION" ]] || die '--consumer-solution is required'
((${#ALLOWS[@]} > 0)) || die 'at least one --allow path is required'

collab_profile_save delivery ISSUE BRANCH TITLE CARRIER PROVIDER_SOLUTION CONSUMER_ROOT CONSUMER_SOLUTION TOOLS_DIR OUTPUT_PREFIX SKIP_APPLY ALLOWS FOCUSED_TESTS AUDIT_SCOPES

for command in git bash dotnet python3 sha256sum; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

for tool in \
  collab-repo-state.sh \
  collab-dx-inspect.sh \
  collab-dx-apply-checked.sh \
  collab-git-change-audit.sh \
  collab-work-verify.sh; do
  [[ -x "$TOOLS_DIR/$tool" ]] || die "required executable tool missing: $TOOLS_DIR/$tool"
done

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die 'not inside a Git repository'
cd "$ROOT"
mkdir -p .dx

CARRIER_ABS=$(python3 - "$CARRIER" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)
[[ -f "$CARRIER_ABS" ]] || die "carrier not found: $CARRIER"
[[ -f "$PROVIDER_SOLUTION" ]] || die "provider solution not found: $PROVIDER_SOLUTION"
[[ -d "$CONSUMER_ROOT" ]] || die "consumer root not found: $CONSUMER_ROOT"
[[ -f "$CONSUMER_ROOT/$CONSUMER_SOLUTION" ]] || die "consumer solution not found: $CONSUMER_ROOT/$CONSUMER_SOLUTION"

LOG_DIR="$ROOT/.dx/${OUTPUT_PREFIX}-run"
rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"
MASTER_LOG="$LOG_DIR/master.log"
FAILURE_REPORT="$ROOT/.dx/${OUTPUT_PREFIX}-failure-report.txt"
FINAL_CARRIER="$ROOT/.dx/${OUTPUT_PREFIX}-final.dx.txt"
FINAL_EVIDENCE="$ROOT/.dx/${OUTPUT_PREFIX}-delivery-evidence.txt"
FINAL_REPORT="$ROOT/.dx/${OUTPUT_PREFIX}-delivery-report.txt"
UPLOAD_MANIFEST="$ROOT/.dx/${OUTPUT_PREFIX}-upload-manifest.txt"
CURRENT_PHASE="initialization"

exec > >(tee -a "$MASTER_LOG") 2>&1

write_failure_report() {
  local status=$1
  {
    printf '# Delivery Workflow Failure\n\n'
    printf -- '- Repository: %s\n' "$(git remote get-url origin 2>/dev/null || printf unknown)"
    printf -- '- Issue: #%s\n' "$ISSUE"
    printf -- '- Expected branch: %s\n' "$BRANCH"
    printf -- '- Phase: %s\n' "$CURRENT_PHASE"
    printf -- '- Exit status: %s\n' "$status"
    printf -- '- HEAD: %s\n' "$(git rev-parse HEAD 2>/dev/null || printf unavailable)"
    printf '\n## Git status\n\n```text\n'
    git status --short 2>&1 || true
    printf '```\n\n## Last 160 workflow lines\n\n```text\n'
    tail -n 160 "$MASTER_LOG" 2>/dev/null || true
    printf '```\n\n## Files to upload for correction\n\n'
    printf '1. `%s`\n' "$FAILURE_REPORT"
    printf '2. `%s`\n' "$MASTER_LOG"
    if [[ -f "$LOG_DIR/${CURRENT_PHASE}.txt" ]]; then
      printf '3. `%s`\n' "$LOG_DIR/${CURRENT_PHASE}.txt"
    else
      printf '3. `%s`\n' "$CARRIER_ABS"
    fi
    printf '\nDo not rerun the failed phase until its output has been inspected.\n'
  } > "$FAILURE_REPORT"

  printf '\n=== FAILURE PACKAGE ===\n'
  printf 'Workflow stopped during: %s\n' "$CURRENT_PHASE"
  printf 'Upload these files for correction:\n'
  printf '1. %s\n' "$FAILURE_REPORT"
  printf '2. %s\n' "$MASTER_LOG"
  if [[ -f "$LOG_DIR/${CURRENT_PHASE}.txt" ]]; then
    printf '3. %s\n' "$LOG_DIR/${CURRENT_PHASE}.txt"
  else
    printf '3. %s\n' "$CARRIER_ABS"
  fi
}

on_error() {
  local status=$?
  trap - ERR
  write_failure_report "$status"
  exit "$status"
}
trap on_error ERR

run_phase() {
  local phase=$1
  shift
  CURRENT_PHASE=$phase
  printf '\n=== %s ===\n' "$phase"
  "$@" 2>&1 | tee "$LOG_DIR/${phase}.txt"
}

run_shell_phase() {
  local phase=$1
  shift
  CURRENT_PHASE=$phase
  printf '\n=== %s ===\n' "$phase"
  bash -o pipefail -c "$*" 2>&1 | tee "$LOG_DIR/${phase}.txt"
}

CURRENT_PHASE="preflight"
ACTUAL_BRANCH=$(git branch --show-current)
[[ "$ACTUAL_BRANCH" == "$BRANCH" ]] || die "expected branch '$BRANCH', found '$ACTUAL_BRANCH'"
DEFAULT_BRANCH=$(git remote show origin | sed -n '/HEAD branch/s/.*: //p')
[[ -n "$DEFAULT_BRANCH" ]] || die 'could not determine default branch'
[[ "$ACTUAL_BRANCH" != "$DEFAULT_BRANCH" ]] || die 'refusing to work on the default branch'
git diff --check
git diff --cached --check

run_phase repo-state-start "$TOOLS_DIR/collab-repo-state.sh"

CURRENT_PHASE="carrier-inspection"
{
  printf '=== SUMMARY ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS"
  printf '=== FILE LIST ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --list
  printf '=== HASHES ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --hashes
  printf '=== READONLY TARGETS ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --readonly
  printf '=== WHOLE CARRIER SHA-256 ===\n'
  sha256sum "$CARRIER_ABS"
} 2>&1 | tee "$LOG_DIR/carrier-inspection.txt"

READONLY_OUTPUT=$($TOOLS_DIR/collab-dx-inspect.sh "$CARRIER_ABS" --readonly)
[[ -z "$READONLY_OUTPUT" ]] || die 'carrier contains readonly targets'

if ((SKIP_APPLY == 0)); then
  run_phase carrier-application "$TOOLS_DIR/collab-dx-apply-checked.sh" "$CARRIER_ABS"
else
  CURRENT_PHASE="carrier-application-equivalence"
  printf '\n=== carrier-application-equivalence ===\n'
  while IFS= read -r path; do
    [[ -f "$path" ]] || die "carrier path is absent during --skip-apply: $path"
    expected=$(mktemp)
    "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --file "$path" > "$expected"
    cmp -s -- "$expected" "$path" || { rm -f "$expected"; die "carrier payload differs from working tree during --skip-apply: $path"; }
    rm -f "$expected"
      done < <(
        "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --list |
          tr -d '\r'
      )
  printf 'PASS: carrier payloads equal current working-tree files.\n' | tee "$LOG_DIR/carrier-application-equivalence.txt"
fi

for project in "${FOCUSED_TESTS[@]}"; do
  safe=$(printf '%s' "$project" | tr '/\\: ' '____')
  run_phase "focused-test-${safe}" dotnet test "$project" --logger 'console;verbosity=normal'
done

CURRENT_PHASE="architecture-audit"
AUDIT_PATHS=(src tests)
if ((${#AUDIT_SCOPES[@]} > 0)); then
  AUDIT_PATHS=("${AUDIT_SCOPES[@]}")
fi
{
  printf '=== ACTION LOG AND COMMAND COLLECTION REPRESENTATIONS ===\n'
  git grep -nE 'ActionLog|IReadOnlyList<.*Command|List<.*Command' -- "${AUDIT_PATHS[@]}" || true
  printf '=== APPEND PATHS ===\n'
  git grep -nE '\.Append\(command\)|ActionLog.*Add|Add\(command\)' -- "${AUDIT_PATHS[@]}" || true
  printf '=== ACTION COUNT STORAGE ===\n'
  git grep -nE 'ActionCount[[:space:]]*\{[[:space:]]*get;|ActionCount[[:space:]]*=' -- "${AUDIT_PATHS[@]}" || true
  printf '=== CLAMPING OR REPAIR ===\n'
  git grep -nEi 'clamp|Math\.Min|Math\.Max|normalize|repair|modulo' -- "${AUDIT_PATHS[@]}" || true
  printf '=== MUTABLE PUBLIC COLLECTIONS ===\n'
  git grep -nE 'public .*List<|public .*\[\]|IList<|ICollection<' -- "${AUDIT_PATHS[@]}" || true
  printf '=== ALTERNATIVE REDUCERS ===\n'
  git grep -nEi 'alternative.*replay|alternative.*reducer|reducer|preview.*replay' -- "${AUDIT_PATHS[@]}" || true
  printf '=== GAME-SPECIFIC GENERIC NOUNS ===\n'
  git grep -nEi 'First Bloom|FirstBloom|Bloom|Fertile|Barren|Moss|Mycelium|Stone|enclosure|placement|score' -- src/Verdant.Core src/Verdant.Replay 2>/dev/null || true
  printf '=== PROHIBITED DETERMINISTIC DEPENDENCIES ===\n'
  git grep -nEi 'storage|persist|browser|presentation|audio|haptic|analytics|DateTime|DateTimeOffset|Guid|Random|IClock|host' -- src/Verdant.Core src/Verdant.Replay 2>/dev/null || true
  printf '=== PROJECT REFERENCES ===\n'
  git grep -n 'ProjectReference' -- '*.csproj' || true
  printf '=== COPIED VERDANT SOURCE ===\n'
  git grep -nEi 'Compile Include=.*Verdant|Link=.*Verdant' -- '*.csproj' || true
  printf '=== TRACKED BUILD ARTIFACTS ===\n'
  git ls-files | grep -E '(^|/)(bin|obj)/' || true
} 2>&1 | tee "$LOG_DIR/architecture-audit.txt"

run_phase provider-build dotnet build "$PROVIDER_SOLUTION"
run_phase provider-tests dotnet test "$PROVIDER_SOLUTION" --no-build --logger 'console;verbosity=normal'

CURRENT_PHASE="consumer-build"
(
  cd "$CONSUMER_ROOT"
  dotnet build "$CONSUMER_SOLUTION"
) 2>&1 | tee "$LOG_DIR/consumer-build.txt"

CURRENT_PHASE="consumer-tests"
(
  cd "$CONSUMER_ROOT"
  dotnet test "$CONSUMER_SOLUTION" --no-build --logger 'console;verbosity=normal'
) 2>&1 | tee "$LOG_DIR/consumer-tests.txt"

CURRENT_PHASE="stage-delivery"
mapfile -t CARRIER_PATHS < <(
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --list |
    tr -d "\r"
)
  "$TOOLS_DIR/collab-dx-inspect.sh" "$CARRIER_ABS" --list |
    tr -d '\r'

((${#CARRIER_PATHS[@]} > 0)) || die 'carrier contains no files'
git add -- "${CARRIER_PATHS[@]}"

mapfile -t CHANGED_PATHS < <({ git diff --name-only; git diff --cached --name-only; } | sort -u)
((${#CHANGED_PATHS[@]} > 0)) || die 'no changed paths found after application'

for path in "${CHANGED_PATHS[@]}"; do
  allowed=0
  for prefix in "${ALLOWS[@]}"; do
    prefix=${prefix%/}
    if [[ "$path" == "$prefix" || "$path" == "$prefix/"* ]]; then
      allowed=1
      break
    fi
  done
  ((allowed == 1)) || die "changed path is outside declared scope: $path"
done

AUDIT_ARGS=()
for path in "${ALLOWS[@]}"; do
  AUDIT_ARGS+=(--allow "$path")
done
run_phase restricted-change-audit "$TOOLS_DIR/collab-git-change-audit.sh" "${AUDIT_ARGS[@]}"
run_phase work-verify "$TOOLS_DIR/collab-work-verify.sh"
run_phase repo-state-final "$TOOLS_DIR/collab-repo-state.sh"

CURRENT_PHASE="final-carrier"
pack_args=()
for path in "${CHANGED_PATHS[@]}"; do pack_args+=(--path "$path"); done
python3 "$SCRIPT_DIR/collab-dx-pack.py" --out "$FINAL_CARRIER" "${pack_args[@]}"

{
  printf '=== SUMMARY ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$FINAL_CARRIER"
  printf '=== FILE LIST ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$FINAL_CARRIER" --list
  printf '=== HASHES ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$FINAL_CARRIER" --hashes
  printf '=== READONLY TARGETS ===\n'
  "$TOOLS_DIR/collab-dx-inspect.sh" "$FINAL_CARRIER" --readonly
  printf '=== WHOLE CARRIER SHA-256 ===\n'
  sha256sum "$FINAL_CARRIER"
} 2>&1 | tee "$LOG_DIR/final-carrier-inspection.txt"

FINAL_READONLY=$($TOOLS_DIR/collab-dx-inspect.sh "$FINAL_CARRIER" --readonly)
[[ -z "$FINAL_READONLY" ]] || die 'final carrier contains readonly targets'

CURRENT_PHASE="evidence-package"
{
  printf '===== DELIVERY IDENTITY =====\n'
  printf 'Repository: %s\n' "$(git remote get-url origin)"
  printf 'Primary issue: #%s\n' "$ISSUE"
  printf 'Branch: %s\n' "$BRANCH"
  printf 'Proposed PR title: %s\n' "$TITLE"
  printf 'HEAD: %s\n' "$(git rev-parse HEAD)"
  printf '\n===== FINAL CARRIER INSPECTION =====\n'
  cat "$LOG_DIR/final-carrier-inspection.txt"
  for file in "$LOG_DIR"/*.txt; do
    [[ "$file" == "$LOG_DIR/final-carrier-inspection.txt" ]] && continue
    printf '\n===== %s =====\n' "$(basename "$file" .txt)"
    cat "$file"
  done
  printf '\n===== FINAL GIT STATUS =====\n'
  git status --short
  printf '\n===== STAGED NAME STATUS =====\n'
  git diff --cached --find-renames --name-status
  printf '\n===== STAGED DIFF CHECK =====\n'
  git diff --cached --check
  printf '\n===== CURRENT PR =====\n'
  if command -v gh >/dev/null 2>&1; then
    gh pr list --head "$BRANCH" --state open --json number,title,state,url
  else
    printf 'gh not available; PR state not queried\n'
  fi
} > "$FINAL_EVIDENCE" 2>&1

CARRIER_HASH=$(sha256sum "$FINAL_CARRIER" | awk '{print $1}')
{
  printf '# PR Delivery\n\n'
  printf '## Identity\n\n'
  printf -- '- Repository: `%s`\n' "$(git remote get-url origin)"
  printf -- '- Primary issue: `#%s`\n' "$ISSUE"
  printf -- '- Branch: `%s`\n' "$BRANCH"
  printf -- '- Proposed PR title: `%s`\n' "$TITLE"
  printf -- '- Current HEAD: `%s`\n\n' "$(git rev-parse HEAD)"
  printf '## DX carrier\n\n'
  printf -- '- File: `%s`\n' "$FINAL_CARRIER"
  printf -- '- DX version: `v1.3.1`\n'
  printf -- '- SHA-256: `%s`\n' "$CARRIER_HASH"
  printf -- '- Included paths:\n'
  for path in "${CHANGED_PATHS[@]}"; do printf '  - `%s`\n' "$path"; done
  printf '\n## Verification\n\n'
  printf -- '- Carrier inspection: PASS\n'
  printf -- '- Restricted change audit: PASS\n'
  printf -- '- Provider build and tests: PASS\n'
  printf -- '- Consumer build and tests: PASS\n'
  printf -- '- Full work verification: PASS\n\n'
  printf '## Repository state\n\n'
  printf -- '- Staged files: %s\n' "${#CHANGED_PATHS[@]}"
  printf -- '- Conflicts: none\n'
  printf -- '- PR created: no\n\n'
  printf '## Requested assessment\n\n'
  printf 'Please assess this bounded delivery for Issue #%s. I have not created the PR or started the following PR.\n' "$ISSUE"
} > "$FINAL_REPORT"

{
  printf 'Upload exactly these three files:\n'
  printf '1. %s\n' "$FINAL_CARRIER"
  printf '2. %s\n' "$FINAL_EVIDENCE"
  printf '3. %s\n' "$FINAL_REPORT"
  printf '\nSHA-256:\n'
  sha256sum "$FINAL_CARRIER" "$FINAL_EVIDENCE" "$FINAL_REPORT"
} > "$UPLOAD_MANIFEST"

CURRENT_PHASE="final-validation"
python3 - "$FINAL_CARRIER" "$FINAL_EVIDENCE" "$FINAL_REPORT" <<'PY'
from pathlib import Path
import sys

carrier, evidence, report = map(Path, sys.argv[1:])
for path in (carrier, evidence, report):
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f'ERROR: missing or empty final artifact: {path}')

text = carrier.read_text(encoding='utf-8')
if not text.startswith('%%DX v1.3.1\n'):
    raise SystemExit('ERROR: final carrier is not DX v1.3.1')
if 'readonly="true"' in text:
    raise SystemExit('ERROR: final carrier contains a readonly target')
if text.count('%%FILE ') != text.count('%%ENDBLOCK'):
    raise SystemExit('ERROR: final carrier block counts differ')

required = (
    'restricted-change-audit',
    'provider-build',
    'provider-tests',
    'consumer-build',
    'consumer-tests',
    'work-verify',
    'repo-state-final',
)
evidence_text = evidence.read_text(encoding='utf-8')
for marker in required:
    if marker not in evidence_text:
        raise SystemExit(f'ERROR: evidence is missing section: {marker}')

print('PASS: final carrier, evidence, and report are complete')
PY

collab_profile_save pr ISSUE TITLE BRANCH FINAL_REPORT FINAL_EVIDENCE FINAL_CARRIER
    collab_record_run delivery success "$FINAL_CARRIER" "$FINAL_EVIDENCE" "$FINAL_REPORT" >/dev/null
trap - ERR
printf '\n=== DELIVERY READY ===\n'
cat "$UPLOAD_MANIFEST"
printf '\nThe script did not commit, push, create a PR, merge, or start another PR.\n'