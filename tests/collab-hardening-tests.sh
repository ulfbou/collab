#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P);ROOT=$(mktemp -d);trap 'rm -rf "$ROOT"' EXIT;cp "$HERE/collab-state.py" "$HERE/collab-dx-pack.py" "$HERE/dx.py" "$ROOT"/;cp -R "$HERE/collab" "$ROOT/";cd "$ROOT";git init -q;git config user.email test@example.invalid;git config user.name Test;git remote add origin https://github.com/example/repo.git;echo x>README;git add README;git commit -qm init
pass(){ printf 'PASS: %s\n' "$1"; }
json='{"branch":"test/example"}';python3 collab-state.py save session --json "$json";[[ $(python3 collab-state.py load session|python3 -c 'import json,sys;print(json.load(sys.stdin)["branch"])') == test/example ]];pass scalar-profile
json='{"issue":"10","branch":"test/example","title":"T","carrier":"c","providerSolution":"p","consumerRoot":"r","consumerSolution":"s","toolsDir":"t","outputPrefix":"o","skipApply":false,"allows":["a b","ü"],"focusedTests":[],"auditScopes":[]}'
python3 collab-state.py save delivery --json "$json";[[ $(python3 collab-state.py load delivery|python3 -c 'import json,sys;print(len(json.load(sys.stdin)["allows"]))') == 2 ]];pass array-profile
printf '{bad' > .dx/collab/profiles/session.json;! python3 collab-state.py load session 2>/dev/null;pass malformed-json
rm .dx/collab/profiles/session.json;echo ok > 'a b.txt';git add 'a b.txt';python3 collab-dx-pack.py --out out.dx --path 'a b.txt' >/dev/null;grep -q '%%FILE path="a b.txt"' out.dx;pass unicode-safe-text
printf 'bad\r\n' > crlf.txt
python3 collab-dx-pack.py --out crlf.dx --path crlf.txt >/dev/null
grep -q 'path="crlf.txt" encoding="base64"' crlf.dx
python3 dx.py unpack crlf.dx crlf-out --quiet
cmp -s crlf.txt crlf-out/crlf.txt
pass crlf-preserved

printf 'bad' > nonewline.txt
python3 collab-dx-pack.py --out nonewline.dx --path nonewline.txt >/dev/null
python3 dx.py inspect nonewline.dx --file nonewline.txt |
  cmp - <(printf 'bad')
pass missing-newline-preserved

printf '\0' > binary
python3 collab-dx-pack.py --out x.dx --path binary >/dev/null
grep -q 'path="binary" encoding="base64"' x.dx
python3 dx.py unpack x.dx binary-out --quiet
cmp -s binary binary-out/binary
pass binary-preserved
ids=$(for i in {1..20};do python3 collab-state.py run-id;done);[[ $(sort -u<<<"$ids"|wc -l) == 20 ]];pass unique-run-ids