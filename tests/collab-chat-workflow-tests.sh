#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export COLLAB_SOURCE_ROOT="$HERE"

cd "$TMP"
git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/chat-workflow.git
printf '# Repository\n' > README.md
git add README.md
git commit -qm init
git branch -M main
mkdir -p .git/refs/remotes/origin bin
printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD
cat > bin/gh <<'EOF'
#!/usr/bin/env bash
if [[ ${1:-} == auth && ${2:-} == status ]]; then exit 1; fi
exit 99
EOF
chmod +x bin/gh
export COLLAB_GH_BIN="$PWD/bin/gh"

before=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
"$HERE/collab-chat-start.sh" --repo example/chat-workflow --no-github --dry-run >/dev/null
after=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
[[ $before == "$after" ]]
printf 'PASS: start dry-run performs no writes\n'

"$HERE/collab-chat-start.sh" --repo example/chat-workflow --no-github >/dev/null
test -s .dx/collab/lead-chat-start.dx.txt
grep -q '^%%DX v1.3.1$' .dx/collab/lead-chat-start.dx.txt
grep -q '^%%FILE path="repository-state.json" readonly="true"$' .dx/collab/lead-chat-start.dx.txt
grep -q '^%%FILE path="repository-evidence.dx.txt" readonly="true"$' .dx/collab/lead-chat-start.dx.txt
printf 'PASS: one-file Lead startup package generated\n'

head=$(git rev-parse HEAD)
cat > selection.json <<EOF
{
  "schemaVersion": "1.0",
  "decision": "START_EXISTING_ISSUE",
  "repository": "example/chat-workflow",
  "evidenceHead": "$head",
  "summary": "Implement the bounded chat workflow.",
  "nextConversation": "SENIOR",
  "details": {
    "issue": {"number": 7, "title": "Implement chat workflow"},
    "work": {"objective": "Complete the validated workflow.", "nonGoals": ["Do not change PR finalization."], "allowedPaths": ["collab-chat.py", "tests"]},
    "pr": {"branch": "feat/conversation-bootstrap", "title": "Implement conversation bootstrap"},
    "verification": {"focusedTests": ["tests/collab-chat-workflow-tests.sh"], "providerSolution": "", "requiredConsumers": []}
  }
}
EOF
cat > decision.md <<'EOF'
# LEAD DECISION

Start the existing issue as one bounded delivery.
EOF
cat > delivery-brief.md <<'EOF'
# Delivery Brief

Implement the validated bounded workflow and run the complete shell test.
EOF
cat > senior-kickstart.md <<'EOF'
# Senior Kickstart

Read the package and implement the complete accepted delivery.
EOF
printf '{"files":["collab-chat.py","tests/collab-chat-workflow-tests.sh"]}\n' > required-evidence.json
python3 - <<'PY'
from pathlib import Path
import importlib.util
import os

s=importlib.util.spec_from_file_location(
    'c',
    os.path.join(os.environ['COLLAB_SOURCE_ROOT'],'collab-chat.py'),
)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)

files={
    name:Path(name).read_bytes()
    for name in (
        'selection.json',
        'decision.md',
        'delivery-brief.md',
        'senior-kickstart.md',
        'required-evidence.json',
    )
}
Path('lead-selection.dx.txt').write_bytes(m.dx_pack(files,False))
PY
"$HERE/collab-chat-accept.sh" lead-selection.dx.txt --dry-run | grep -q 'VALID: START_EXISTING_ISSUE'
test ! -e .dx/collab/accepted-selection.dx.txt
printf 'PASS: selection dry-run validates without acceptance writes\n'
"$HERE/collab-chat-accept.sh" lead-selection.dx.txt >/dev/null
test -s .dx/collab/accepted-selection.dx.txt
test -s .dx/collab/senior-chat-start.dx.txt
grep -q '^%%FILE path="delivery-brief.md" readonly="true"$' .dx/collab/senior-chat-start.dx.txt
printf 'PASS: valid Lead selection generates one-file Senior package\n'

sed -i 's#feat/conversation-bootstrap#feat/issue-7-bootstrap#' selection.json
python3 - <<'PY'
from pathlib import Path
import importlib.util
import os

s=importlib.util.spec_from_file_location(
    'c',
    os.path.join(os.environ['COLLAB_SOURCE_ROOT'],'collab-chat.py'),
)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
PY
! "$HERE/collab-chat-accept.sh" bad-selection.dx.txt --dry-run >/dev/null 2>&1
printf 'PASS: branch names containing issue numbers are rejected\n'

"$HERE/collab-chat-start.sh" --repo example/chat-workflow --no-github --include README.md --out .dx/collab/included.dx.txt >/dev/null
python3 - <<'PY'
from pathlib import Path
import importlib.util
import os

s=importlib.util.spec_from_file_location(
    'c',
    os.path.join(os.environ['COLLAB_SOURCE_ROOT'],'collab-chat.py'),
)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
outer,_=m.dx_parse(Path('.dx/collab/included.dx.txt'))
inner=Path('inner.dx.txt'); inner.write_bytes(outer['repository-evidence.dx.txt'])
files,_=m.dx_parse(inner); inner.unlink()
assert set(files)=={'repository/README.md'}, set(files)
PY
printf 'PASS: include paths restrict repository evidence deterministically\n'

printf '{"files":"not-an-array"}\n' > required-evidence.json
python3 - <<'PY'
from pathlib import Path
import importlib.util
import os

s=importlib.util.spec_from_file_location(
    'c',
    os.path.join(os.environ['COLLAB_SOURCE_ROOT'],'collab-chat.py'),
)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
files={n:Path(n).read_bytes() for n in ('selection.json','decision.md','delivery-brief.md','senior-kickstart.md','required-evidence.json')}
Path('bad-evidence.dx.txt').write_bytes(m.dx_pack(files,False))
PY
! "$HERE/collab-chat-accept.sh" bad-evidence.dx.txt --dry-run >/dev/null 2>&1
printf 'PASS: malformed required-evidence contract is rejected\n'

cat > selection.json <<EOF
{
  "schemaVersion":"1.0",
  "decision":"USER_DECISION_REQUIRED",
  "repository":"example/chat-workflow",
  "evidenceHead":"$head",
  "summary":"Resolve one product choice.",
  "nextConversation":"NONE",
  "details":{
    "question":"Which compatibility policy applies?",
    "whyUnresolved":"Two accepted alternatives have no precedence rule.",
    "options":[
      {"name":"Strict","consequences":["Reject mismatches."]},
      {"name":"Bridge","consequences":["Maintain an adapter."]}
    ],
    "recommendation":"Use strict compatibility."
  }
}
EOF
python3 - <<'PY'
from pathlib import Path
import importlib.util
import os

s=importlib.util.spec_from_file_location(
    'c',
    os.path.join(os.environ['COLLAB_SOURCE_ROOT'],'collab-chat.py'),
)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
Path('user-decision.dx.txt').write_bytes(m.dx_pack({'selection.json':Path('selection.json').read_bytes(),'decision.md':b'# LEAD DECISION\n\nA product choice is required.\n'},False))
PY
"$HERE/collab-chat-accept.sh" user-decision.dx.txt --dry-run | grep -q 'VALID: USER_DECISION_REQUIRED'
printf 'PASS: user decision requires no artificial planning-change file\n'
