#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tools" "$TMP/bin"
cp "$HERE/collab-pr-finalize.sh" "$HERE/lib-common.sh" "$TMP/tools/"
cat > "$TMP/tools/collab-work-verify.sh" <<'EOF'
#!/usr/bin/env bash
printf 'verify\n' >> "$CALL_LOG"
EOF
cat > "$TMP/tools/collab-repo-verify.sh" <<'EOF'
#!/usr/bin/env bash
printf 'repo-verify\n' >> "$CALL_LOG"
EOF
chmod +x "$TMP/tools/"*.sh
cat >> "$TMP/tools/lib-common.sh" <<'EOF'

# Test-only state boundary. These PR boundary tests validate command ordering and
# mutation boundaries, not persistent collaboration profile semantics.
collab_state() {
  case "${1:-}" in
    load) printf '{}\n' ;;
    save|clear|record) return 0 ;;
    run-id) printf '20260817T000000.000000000Z-1-00000000\n' ;;
    *) return 1 ;;
  esac
}
EOF
cd "$TMP"; git init -q; printf "/bin/\n/tools/\n" >> .git/info/exclude; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/finalize.git
printf 'base\n' > file; git add file; git commit -qm init; git branch -M main; git switch -qc test/finalize
head=$(git rev-parse HEAD); mkdir -p .git/refs/remotes/origin; printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD
export CALL_LOG="$TMP/.git/calls.log" HEAD_OID="$head"
cat > "$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$CALL_LOG"
case "$*" in
 *'pr view'*'statusCheckRollup'*) printf '{"state":"OPEN","isDraft":false,"baseRefName":"main","headRefName":"test/finalize","headRefOid":"%s","mergeable":"MERGEABLE","statusCheckRollup":[],"url":"https://github.com/example/finalize/pull/9"}\n' "$HEAD_OID" ;;
 *'pr merge'*) exit 0 ;;
 *'pr view'*'mergedAt'*) printf '{"state":"MERGED","mergedAt":"2026-08-15T00:00:00Z","mergeCommit":{"oid":"abc"},"url":"https://github.com/example/finalize/pull/9"}\n' ;;
esac
EOF
real_git=$(command -v git)
cat > "$TMP/bin/git" <<EOF
#!/usr/bin/env bash
case "\$1 \${2:-}" in
 'switch main') printf 'git switch main\n' >> "\$CALL_LOG"; exit 0 ;;
 'pull --ff-only') printf 'git pull\n' >> "\$CALL_LOG"; exit 0 ;;
esac
exec "$real_git" "\$@"
EOF
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH"
bash "$TMP/tools/collab-pr-finalize.sh" 9 >/dev/null
grep -q '^verify$' "$CALL_LOG"; grep -q '^gh pr merge ' "$CALL_LOG"; grep -q '^git switch main$' "$CALL_LOG"; grep -q '^git pull$' "$CALL_LOG"; grep -q '^repo-verify$' "$CALL_LOG"
verify_n=$(grep -n '^verify$' "$CALL_LOG"|cut -d: -f1); merge_n=$(grep -n '^gh pr merge ' "$CALL_LOG"|cut -d: -f1); switch_n=$(grep -n '^git switch main$' "$CALL_LOG"|cut -d: -f1); repo_n=$(grep -n '^repo-verify$' "$CALL_LOG"|cut -d: -f1)
((verify_n < merge_n && merge_n < switch_n && switch_n < repo_n)); printf 'PASS: finalization verifies before merge and verifies repository after synchronization\n'