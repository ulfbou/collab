#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tools" "$TMP/bin"; cp "$HERE/collab-pr-create.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$TMP/tools/"
cat > "$TMP/tools/collab-work-verify.sh" <<'EOF'
#!/usr/bin/env bash
printf 'MUTATION:verify\n' >> "$CALL_LOG"; exit 99
EOF
chmod +x "$TMP/tools/"*.sh "$TMP/tools/collab-state.py"
cat > "$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$CALL_LOG"
case "$*" in 'auth status') exit 0;; *'pr list'*) printf '[]\n';; *'issue view'*) printf '{"state":"OPEN","labels":[],"milestone":null}\n';; *) printf 'MUTATION:unexpected gh command\n' >> "$CALL_LOG"; exit 98;; esac
EOF
chmod +x "$TMP/bin/gh"
cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/repo.git; printf 'base\n' > file; git add file; git commit -qm init; git branch -M main; git switch -qc test/dry-run; mkdir -p .git/refs/remotes/origin; printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD
export PATH="$TMP/bin:$PATH" CALL_LOG="$TMP/calls.log"; before_head=$(git rev-parse HEAD); before_status=$(git status --porcelain=v1 --untracked-files=all)
body=$'Closes #10\n\n## Summary\n\nDry run.\n\n## Verification\n\n- Planned.'
bash "$TMP/tools/collab-pr-create.sh" --issue 10 --title Dry --body "$body" --dry-run >/dev/null
after_head=$(git rev-parse HEAD); after_status=$(git status --porcelain=v1 --untracked-files=all)
[[ $before_head == "$after_head" && $before_status == "$after_status" ]]; [[ ! -e .dx/collab ]]; ! grep -q '^MUTATION:' "$CALL_LOG"
printf 'PASS: PR dry-run performs no local, profile, verification, push, or GitHub mutation\n'