#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tools" "$TMP/bin"
cp "$HERE/collab-pr-create.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$TMP/tools/"
cat > "$TMP/tools/collab-work-verify.sh" <<'EOF'
#!/usr/bin/env bash
printf 'verify\n' >> "$CALL_LOG"
EOF
chmod +x "$TMP/tools/"*.sh "$TMP/tools/collab-state.py"
cat > "$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %q' "$1" >> "$CALL_LOG"; shift || true; printf ' %q' "$@" >> "$CALL_LOG"; printf '\n' >> "$CALL_LOG"
case "$*" in
  'auth status') exit 0 ;;
  *'pr list'*) printf '[]\n' ;;
  *'issue view'*) printf '{"state":"OPEN","labels":[],"milestone":null}\n' ;;
  *'pr create'*) printf 'https://github.com/example/repo/pull/7\n' ;;
  *'pr view'*) printf '{"number":7,"url":"https://github.com/example/repo/pull/7","headRefOid":"HEAD_PLACEHOLDER"}\n' ;;
esac
EOF
chmod +x "$TMP/bin/gh"
cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/repo.git
printf 'base\n' > file.txt; git add file.txt; git commit -qm init; git branch -M main; git switch -qc test/command-order
head=$(git rev-parse HEAD); sed -i "s/HEAD_PLACEHOLDER/$head/" "$TMP/bin/gh"
mkdir -p .git/refs/remotes/origin; printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD
export PATH="$TMP/bin:$PATH" CALL_LOG="$TMP/calls.log"
printf 'change\n' >> file.txt; git add file.txt
body=$'Closes #10\n\n## Summary\n\nComplete change.\n\n## Verification\n\n- Verified.'
# Replace git push transport with a repository-local wrapper while delegating all other git commands.
real_git=$(command -v git)
cat > "$TMP/bin/git" <<EOF
#!/usr/bin/env bash
if [[ \$1 == push ]]; then printf 'git push\n' >> "\$CALL_LOG"; exit 0; fi
exec "$real_git" "\$@"
EOF
chmod +x "$TMP/bin/git"
bash "$TMP/tools/collab-pr-create.sh" --issue 10 --title 'Test command order' --body "$body" >/dev/null
commit_line=$(grep -n '^\[\|git push' "$CALL_LOG" 2>/dev/null || true)
grep -q '^verify$' "$CALL_LOG"
grep -q '^git push$' "$CALL_LOG"
grep -q '^gh pr create ' "$CALL_LOG"
push_n=$(grep -n '^git push$' "$CALL_LOG" | cut -d: -f1); create_n=$(grep -n '^gh pr create ' "$CALL_LOG" | cut -d: -f1)
((push_n < create_n)); [[ $(git log -1 --pretty=%s) == 'Test command order' ]]
printf 'PASS: verification, commit, push, and PR creation boundaries preserved\n'