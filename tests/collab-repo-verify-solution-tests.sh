#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cp "$HERE/collab-repo-verify.sh" "$HERE/lib-common.sh" "$TMP/"
chmod +x "$TMP/collab-repo-verify.sh"

cd "$TMP"
git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/optional-solution.git
printf 'base\n' > tracked
git add tracked
git commit -qm init

bash ./collab-repo-verify.sh >/dev/null
printf 'PASS: repository without solution verifies successfully\n'

cat > bin/dotnet <<'DOTNET'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOTNET_LOG"
DOTNET
chmod +x bin/dotnet
export PATH="$TMP/bin:$PATH"
export DOTNET_LOG="$TMP/dotnet.log"

printf '<Solution />\n' > Example.slnx
bash ./collab-repo-verify.sh >/dev/null
grep -Fxq 'build ./Example.slnx' "$DOTNET_LOG"
grep -Fxq 'test ./Example.slnx --no-build' "$DOTNET_LOG"
printf 'PASS: repository with one solution builds and tests it\n'

printf '<Solution />\n' > Second.slnx
if bash ./collab-repo-verify.sh >"$TMP/multiple.out" 2>&1; then
    printf 'ERROR: repository with multiple solutions unexpectedly verified\n' >&2
    exit 1
fi
grep -Fq 'expected at most one solution file, found 2' "$TMP/multiple.out"
printf 'PASS: repository with multiple solutions is rejected\n'