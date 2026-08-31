#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
REPO=ulfbou/mock-repo
BASE=test-base

verify_access(){
    gh auth status >/dev/null
    [[ $(gh repo view "$REPO" --json nameWithOwner --jq .nameWithOwner) == "$REPO" ]]
    [[ $(gh api "repos/$REPO" --jq .permissions.push) == true ]]
    gh api "repos/$REPO/git/ref/heads/$BASE" >/dev/null
}

[[ ${COLLAB_RUN_GITHUB_INTEGRATION:-0} == 1 ]] || {
    echo 'SKIP: set COLLAB_RUN_GITHUB_INTEGRATION=1'
    exit 0
}

bash "$(dirname "$0")/collab-evidence-github-fixture-verify.sh"

U=$(gh api user --jq .login)
ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-$(openssl rand -hex 4)"
B="test/evidence/$U/$ID"

T=$(mktemp -d)
clean(){
    [[ $B == test/evidence/* ]] && git -C "$T/repo" push origin --delete "$B" >/dev/null 2>&1 || true
    rm -rf "$T"
}
trap 'rc=$?; clean; exit $rc' EXIT

gh repo clone "$REPO" "$T/repo" >/dev/null 2>&1
cd "$T/repo"
git switch -c "$B" origin/$BASE --quiet
git push -u origin "$B" >/dev/null 2>&1

printf 'run\n' > run.txt
git add .
git -c user.name=test -c user.email=test@example.invalid commit -m integration
git push >/dev/null 2>&1

PR=$(gh pr create --repo "$REPO" --base "$BASE" --head "$B" --title "[collab-test] $ID" --body 'Ephemeral open PR fixture.' 2>/dev/null)

python3 "$HERE/collab-evidence.py" model --root . --out model.json \
    --include fixtures/included.txt --include fixtures/selected \
    --include fixtures/oversized.txt --include fixtures/binary.bin \
    --include fixtures/non-utf8.bin --include missing

python3 - "$B" <<'PY'
import json, subprocess, sys
m = json.load(open('model.json'))
g = m['git']
assert g['repository'] == 'ulfbou/mock-repo' and g['currentBranch'] == sys.argv[1]
assert g['head'] == subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
assert g['trackedTree'] == sorted(g['trackedTree'])
h = m['github']
assert h['available'] and all(v == 'ok' for v in h['queryStatus'].values())
d = h['data']
assert any(x['title'] == '[collab-fixture] Available issue' and x['body'] for x in d['openIssues'])
assert any(x['title'] == '[collab-fixture] Milestone' and x['description'] and x['due_on'] for x in d['milestones'])
assert any(x['title'].startswith('[collab-test]') for x in d['openPullRequests'])
assert any(x['title'] == '[collab-fixture] Recently merged PR' for x in d['recentlyMergedPullRequests'])
assert d['labels'] == sorted(d['labels'], key=lambda x: x['name'])
assert d['openIssues'] == sorted(d['openIssues'], key=lambda x: x['number'])
f = {x['path']: x for x in m['selectedFiles']}
assert f['fixtures/oversized.txt']['reason'] == 'oversized'
assert f['fixtures/binary.bin']['reason'] == 'binary'
assert f['fixtures/non-utf8.bin']['reason'] == 'non-utf8'
assert f['missing']['status'] == 'missing'
PY

gh pr close "$PR" --repo "$REPO" >/dev/null 2>&1

echo 'PASS: real GitHub collector integration'