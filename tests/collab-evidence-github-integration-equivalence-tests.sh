#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
REPO=ulfbou/mock-repo
BASE=test-base
verify_access(){ gh auth status >/dev/null;[[ $(gh repo view "$REPO" --json nameWithOwner --jq .nameWithOwner)=="$REPO" ]];[[ $(gh api "repos/$REPO" --jq .permissions.push)==true ]];gh api "repos/$REPO/git/ref/heads/$BASE" >/dev/null; }
[[ ${COLLAB_RUN_GITHUB_INTEGRATION:-0} == 1 ]]||{ echo 'SKIP: set COLLAB_RUN_GITHUB_INTEGRATION=1';exit 0;};bash "$(dirname "$0")/collab-evidence-github-fixture-verify.sh";U=$(gh api user --jq .login);ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-$(openssl rand -hex 4)";B="test/evidence/$U/$ID";T=$(mktemp -d);trap 's=$?;[[ $B == test/evidence/* ]]&&git -C "$T/repo" push origin --delete "$B" >/dev/null 2>&1||true;rm -rf "$T";exit $s' EXIT;gh repo clone "$REPO" "$T/repo";cd "$T/repo";git switch -c "$B" origin/$BASE;git push -u origin "$B";cp "$HERE"/collab-{evidence.py,chat.py,chat-start.sh,context-collect.sh,state.py} "$HERE/lib-common.sh" .;cp -r "$HERE/schemas" .;chmod +x collab-*.sh collab-*.py;./collab-context-collect.sh --role lead --repo "$REPO" --include fixtures/selected --out context.md >/dev/null;./collab-chat-start.sh --repo "$REPO" --include fixtures/selected --out start.dx.txt >/dev/null;python3 - <<'PY'
import importlib.util,json
from pathlib import Path
s=importlib.util.spec_from_file_location('c','collab-chat.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);f,_=m.dx_parse(Path('start.dx.txt'));state=json.loads(f['repository-state.json']);md=Path('context.md').read_text();r=state['repository'];assert all(x in md for x in (r['nameWithOwner'],r['defaultBranch'],r['currentBranch'],r['head'],r['workingTree']));schema=json.load(open('schemas/repository-state.schema.json'))
def validate(value, rule, location='$'):
    if 'const' in rule:
        assert value == rule['const'], location
    if 'enum' in rule:
        assert value in rule['enum'], location
    kind = rule.get('type')
    if kind == 'object':
        assert isinstance(value, dict), location
        required = set(rule.get('required', []))
        assert required <= set(value), (
            location,
            sorted(required - set(value)),
        )
        properties = rule.get('properties', {})
        if rule.get('additionalProperties') is False:
            assert set(value) <= set(properties), (
                location,
                sorted(set(value) - set(properties)),
            )
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key], location + '.' + key)
    elif kind == 'array':
        assert isinstance(value, list), location
        if 'items' in rule:
            for index, child in enumerate(value):
                validate(
                    child,
                    rule['items'],
                    f'{location}[{index}]',
                )
    elif kind == 'string':
        assert isinstance(value, str), location
        if 'pattern' in rule:
            import re
            assert re.search(rule['pattern'], value), location
        if rule.get('format') == 'date-time':
            import datetime as dt
            parsed = dt.datetime.fromisoformat(
                value.replace('Z', '+00:00')
            )
            assert parsed.tzinfo is not None, location
    elif kind == 'boolean':
        assert isinstance(value, bool), location
    elif kind == 'integer':
        assert isinstance(value, int) and not isinstance(value, bool), (
            location
        )
validate(state, schema)
PY
echo 'PASS: real production consumer equivalence and schema'