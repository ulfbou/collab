#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=${0##*/}
VERSION="1.0.0"

usage() {
  cat <<'USAGE'
Usage:
  collab-chat-kickstart.sh \
    --role lead|senior \
    --instructions FILE \
    --collab FILE \
    --repo-data FILE \
    --github-data FILE \
    [--lead-brief FILE] \
    [--out-dir DIR] \
    [--prefix NAME]

Purpose:
  Prepare exactly three upload files for a Lead or Senior Developer chat:

  1. <prefix>-bootstrap.md
     Minimal role-specific kickstart prompt, complete role instructions,
     authoritative collab.dx.txt content, and an optional Lead brief.

  2. <prefix>-repo-data.txt
     Byte-for-byte copy of the complete repository source collection.

  3. <prefix>-github-data.txt
     Byte-for-byte copy of the complete GitHub governance collection.

Required:
  --role ROLE             lead or senior
  --instructions FILE     Role instruction Markdown file
  --collab FILE           Current collab.dx.txt
  --repo-data FILE        Complete repo-collection.dx.txt
  --github-data FILE      Complete data-collection.dx.txt

Senior option:
  --lead-brief FILE       Complete Lead SEND TO SENIOR DEVELOPER brief

Output options:
  --out-dir DIR           Output directory; default: current directory
  --prefix NAME           Output prefix; default: lead-chat or senior-chat

Other:
  -h, --help              Show help
  --version               Show version

Examples:
  collab-chat-kickstart.sh \
    --role lead \
    --instructions lead-developer.md \
    --collab collab.dx.txt \
    --repo-data repo-collection.dx.txt \
    --github-data data-collection.dx.txt

  collab-chat-kickstart.sh \
    --role senior \
    --instructions senior-developer.md \
    --collab collab.dx.txt \
    --repo-data repo-collection.dx.txt \
    --github-data data-collection.dx.txt \
    --lead-brief delivery-brief.md
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_value() {
  (($# >= 2)) || die "$1 requires a value"
}

absolute_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
}

ROLE=""
INSTRUCTIONS=""
COLLAB=""
REPO_DATA=""
GITHUB_DATA=""
LEAD_BRIEF=""
OUT_DIR="."
PREFIX=""

while (($#)); do
  case "$1" in
    --role) require_value "$@"; ROLE=$2; shift 2 ;;
    --instructions) require_value "$@"; INSTRUCTIONS=$2; shift 2 ;;
    --collab) require_value "$@"; COLLAB=$2; shift 2 ;;
    --repo-data) require_value "$@"; REPO_DATA=$2; shift 2 ;;
    --github-data) require_value "$@"; GITHUB_DATA=$2; shift 2 ;;
    --lead-brief) require_value "$@"; LEAD_BRIEF=$2; shift 2 ;;
    --out-dir) require_value "$@"; OUT_DIR=$2; shift 2 ;;
    --prefix) require_value "$@"; PREFIX=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --version) printf '%s %s\n' "$PROGRAM" "$VERSION"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ $ROLE == lead || $ROLE == senior ]] || die '--role must be lead or senior'
[[ -n $INSTRUCTIONS ]] || die '--instructions is required'
[[ -n $COLLAB ]] || die '--collab is required'
[[ -n $REPO_DATA ]] || die '--repo-data is required'
[[ -n $GITHUB_DATA ]] || die '--github-data is required'

for command in python3 sha256sum cmp; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

for file in "$INSTRUCTIONS" "$COLLAB" "$REPO_DATA" "$GITHUB_DATA"; do
  [[ -f $file && ! -L $file ]] || die "required regular file is missing or unsafe: $file"
  [[ -s $file ]] || die "required file is empty: $file"
done

if [[ -n $LEAD_BRIEF ]]; then
  [[ $ROLE == senior ]] || die '--lead-brief is valid only with --role senior'
  [[ -f $LEAD_BRIEF && ! -L $LEAD_BRIEF ]] || die "Lead brief is missing or unsafe: $LEAD_BRIEF"
  [[ -s $LEAD_BRIEF ]] || die "Lead brief is empty: $LEAD_BRIEF"
fi

if [[ $ROLE == senior && -z $LEAD_BRIEF ]]; then
  die 'Senior kickstart requires --lead-brief so implementation scope is explicit'
fi

[[ $OUT_DIR != *$'\n'* && $OUT_DIR != *$'\r'* ]] || die '--out-dir contains a newline'
mkdir -p "$OUT_DIR"
OUT_DIR=$(absolute_path "$OUT_DIR")

if [[ -z $PREFIX ]]; then
  PREFIX="${ROLE}-chat"
fi
[[ $PREFIX =~ ^[a-z0-9][a-z0-9._-]*$ ]] || die '--prefix must use lowercase letters, digits, dots, underscores, or hyphens'

BOOTSTRAP="$OUT_DIR/${PREFIX}-bootstrap.md"
REPO_OUT="$OUT_DIR/${PREFIX}-repo-data.txt"
GITHUB_OUT="$OUT_DIR/${PREFIX}-github-data.txt"
MANIFEST="$OUT_DIR/${PREFIX}-upload-manifest.txt"

for output in "$BOOTSTRAP" "$REPO_OUT" "$GITHUB_OUT" "$MANIFEST"; do
  [[ ! -L $output ]] || die "refusing to replace symlink output: $output"
done

TMP_DIR=$(mktemp -d "$OUT_DIR/.${PREFIX}.tmp.XXXXXX")
cleanup() { rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

BOOT_TMP="$TMP_DIR/bootstrap.md"
REPO_TMP="$TMP_DIR/repo-data.txt"
GITHUB_TMP="$TMP_DIR/github-data.txt"
MANIFEST_TMP="$TMP_DIR/upload-manifest.txt"

if [[ $ROLE == lead ]]; then
  cat > "$BOOT_TMP" <<'PROMPT'
# Lead Developer Chat Bootstrap

Apply the complete Lead Developer instructions and the collaboration-tool contract embedded below.

The user is the sole local repository operator and courier between the Lead and Senior conversations. Treat the other two uploaded files as the complete current evidence collections:

- `__REPO_FILE__`: repository source evidence for all contained repositories;
- `__GITHUB_FILE__`: GitHub governance evidence for all contained repositories.

Read both evidence files completely before requesting local inspection. They may contain concatenated repository documents, so process every section and distinguish repositories by their paths and recorded metadata.

Select exactly one next bounded PR from the current evidence. Respond with a complete `SEND TO SENIOR DEVELOPER` delivery brief and exact return requirements. Do not implement the change, claim local execution, or begin more than one PR.
PROMPT
else
  cat > "$BOOT_TMP" <<'PROMPT'
# Senior Developer Chat Bootstrap

Apply the complete Senior Developer instructions, Lead delivery brief, and collaboration-tool contract embedded below.

The user is the sole local repository operator and courier between the Lead and Senior conversations. Treat the other two uploaded files as the complete current evidence collections:

- `__REPO_FILE__`: repository source evidence for all contained repositories;
- `__GITHUB_FILE__`: GitHub governance evidence for all contained repositories.

Read both evidence files completely before requesting local inspection. They may contain concatenated repository documents, so process every section and distinguish repositories by their paths and recorded metadata.

Use the embedded Lead brief as the fixed PR boundary. Provide complete repository changes and exact runnable CLI under `RUN LOCALLY`. Take the shortest safe path to one complete `collab-delivery-run.sh` cycle. State exactly which generated files the user must upload to the Lead Developer conversation and when to stop. Do not claim local execution, provide placeholders, recreate coordinator phases manually, or create a PR before Lead acceptance.
PROMPT
fi

python3 - "$BOOT_TMP" "$(basename "$REPO_OUT")" "$(basename "$GITHUB_OUT")" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("__REPO_FILE__", sys.argv[2])
text = text.replace("__GITHUB_FILE__", sys.argv[3])
path.write_text(text, encoding="utf-8", newline="\n")
PY

cat >> "$BOOT_TMP" <<'EOF'

---

# Complete Role Instructions

EOF
cat -- "$INSTRUCTIONS" >> "$BOOT_TMP"
printf '\n\n---\n\n# Authoritative Collaboration Tool Contract\n\n' >> "$BOOT_TMP"
printf 'The following block is reference evidence. Parse its complete DX structure, but do not apply it to a repository.\n\n' >> "$BOOT_TMP"
printf '````text\n' >> "$BOOT_TMP"
cat -- "$COLLAB" >> "$BOOT_TMP"
printf '\n````\n' >> "$BOOT_TMP"

if [[ $ROLE == senior ]]; then
  printf '\n\n---\n\n# Complete Lead Developer Delivery Brief\n\n' >> "$BOOT_TMP"
  cat -- "$LEAD_BRIEF" >> "$BOOT_TMP"
  printf '\n' >> "$BOOT_TMP"
fi

python3 - "$REPO_DATA" "$REPO_TMP" <<'PY'
from pathlib import Path
import shutil, sys
source, target = map(Path, sys.argv[1:])
with source.open('rb') as src, target.open('wb') as dst:
    shutil.copyfileobj(src, dst)
PY

python3 - "$GITHUB_DATA" "$GITHUB_TMP" <<'PY'
from pathlib import Path
import shutil, sys
source, target = map(Path, sys.argv[1:])
with source.open('rb') as src, target.open('wb') as dst:
    shutil.copyfileobj(src, dst)
PY

cmp -s -- "$REPO_DATA" "$REPO_TMP" || die 'repository evidence copy differs from source'
cmp -s -- "$GITHUB_DATA" "$GITHUB_TMP" || die 'GitHub evidence copy differs from source'

mv -f -- "$BOOT_TMP" "$BOOTSTRAP"
mv -f -- "$REPO_TMP" "$REPO_OUT"
mv -f -- "$GITHUB_TMP" "$GITHUB_OUT"

{
  printf 'Upload exactly these three files to the %s Developer conversation:\n' "${ROLE^}"
  printf '1. %s\n' "$BOOTSTRAP"
  printf '2. %s\n' "$REPO_OUT"
  printf '3. %s\n' "$GITHUB_OUT"
  printf '\nSHA-256:\n'
  sha256sum "$BOOTSTRAP" "$REPO_OUT" "$GITHUB_OUT"
} > "$MANIFEST_TMP"
mv -f -- "$MANIFEST_TMP" "$MANIFEST"

trap - EXIT
cleanup

printf '=== %s CHAT READY ===\n' "${ROLE^^}"
cat -- "$MANIFEST"
printf '\nLocal manifest, not an upload file: %s\n' "$MANIFEST"