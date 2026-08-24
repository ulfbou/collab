#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(mktemp -d);trap 'rm -rf "$ROOT"' EXIT;cp collab-state.py collab-dx-pack.py dx.py "$ROOT"/;cd "$ROOT";git init -q;git config user.email test@example.invalid;git config user.name Test;git remote add origin https://github.com/example/repo.git;echo x>README;git add README;git commit -qm init
pass(){ printf 'PASS: %s\n' "$1"; }
json='{"branch":"test/example"}';python3 collab-state.py save session --json "$json";[[ $(python3 collab-state.py load session|python3 -c 'import json,sys;print(json.load(sys.stdin)["branch"])') == test/example ]];pass scalar-profile
json='{"issue":"10","branch":"test/example","title":"T","carrier":"c","providerSolution":"p","consumerRoot":"r","consumerSolution":"s","toolsDir":"t","outputPrefix":"o","skipApply":false,"allows":["a b","ü"],"focusedTests":[],"auditScopes":[]}'
python3 collab-state.py save delivery --json "$json";[[ $(python3 collab-state.py load delivery|python3 -c 'import json,sys;print(len(json.load(sys.stdin)["allows"]))') == 2 ]];pass array-profile
printf '{bad' > .dx/collab/profiles/session.json;! python3 collab-state.py load session 2>/dev/null;pass malformed-json
rm .dx/collab/profiles/session.json;echo ok > 'a b.txt';git add 'a b.txt';python3 collab-dx-pack.py --out out.dx --path 'a b.txt' >/dev/null;grep -q '%%FILE path="a b.txt"' out.dx;pass unicode-safe-text
printf 'bad\r\n' > crlf.txt;! python3 collab-dx-pack.py --out x.dx --path crlf.txt 2>/dev/null;pass crlf-rejected
printf 'bad' > nonewline.txt;! python3 collab-dx-pack.py --out x.dx --path nonewline.txt 2>/dev/null;pass missing-newline-rejected
printf '\0' > binary;! python3 collab-dx-pack.py --out x.dx --path binary 2>/dev/null;pass binary-rejected
ids=$(for i in {1..20};do python3 collab-state.py run-id;done);[[ $(sort -u<<<"$ids"|wc -l) == 20 ]];pass unique-run-ids