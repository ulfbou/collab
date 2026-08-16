#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-chat.py" "$HERE/collab-chat-start.sh" "$HERE/collab-chat-accept.sh" "$TMP/"
chmod +x "$TMP"/collab-chat.py "$TMP"/*.sh
cd "$TMP"
git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/chat-workflow.git
printf '# Repository\n' > README.md
git add README.md collab-chat.py collab-chat-start.sh collab-chat-accept.sh
git commit -qm init
git branch -M main
mkdir -p .git/refs/remotes/origin
printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD

before=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
./collab-chat-start.sh --repo example/chat-workflow --no-github --dry-run >/dev/null
after=$(find . -mindepth 1 -not -path './.git*' -printf '%P\t%y\t%s\n' | sort)
[[ $before == "$after" ]]
printf 'PASS: start dry-run performs no writes\n'

./collab-chat-start.sh --repo example/chat-workflow --no-github >/dev/null
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
    "verification": {"focusedTests": ["tests/collab-chat-workflow-tests.sh"], "providerSolution": "", "consumerRoot": "", "consumerSolution": ""}
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
import sys
sys.path.insert(0,'.')
import importlib.util
s=importlib.util.spec_from_file_location('c','collab-chat.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
files={n:Path(n).read_bytes() for n in ('selection.json','decision.md','delivery-brief.md','senior-kickstart.md','required-evidence.json')}
Path('lead-selection.dx.txt').write_bytes(m.dx_pack(files,False))
PY
./collab-chat-accept.sh lead-selection.dx.txt --dry-run | grep -q 'VALID: START_EXISTING_ISSUE'
test ! -e .dx/collab/accepted-selection.dx.txt
printf 'PASS: selection dry-run validates without acceptance writes\n'
./collab-chat-accept.sh lead-selection.dx.txt >/dev/null
test -s .dx/collab/accepted-selection.dx.txt
test -s .dx/collab/senior-chat-start.dx.txt
grep -q '^%%FILE path="delivery-brief.md" readonly="true"$' .dx/collab/senior-chat-start.dx.txt
printf 'PASS: valid Lead selection generates one-file Senior package\n'

sed -i 's#feat/conversation-bootstrap#feat/issue-7-bootstrap#' selection.json
python3 - <<'PY'
from pathlib import Path
import importlib.util
s=importlib.util.spec_from_file_location('c','collab-chat.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
files={n:Path(n).read_bytes() for n in ('selection.json','decision.md','delivery-brief.md','senior-kickstart.md','required-evidence.json')}
Path('bad-selection.dx.txt').write_bytes(m.dx_pack(files,False))
PY
! ./collab-chat-accept.sh bad-selection.dx.txt --dry-run >/dev/null 2>&1
printf 'PASS: branch names containing issue numbers are rejected\n'