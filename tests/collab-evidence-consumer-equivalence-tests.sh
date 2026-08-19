#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-chat.py" "$HERE/collab-chat-start.sh" "$HERE/collab-context-collect.sh" "$HERE/lib-common.sh" "$HERE/collab-state.py" "$TMP/"
chmod +x "$TMP"/*.sh "$TMP"/*.py
cd "$TMP"
git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/equivalence.git
printf 'shared\n' > shared.txt
git add .
git commit -qm init
git branch -M main
mkdir -p .git/refs/remotes/origin
printf 'ref: refs/remotes/origin/main\n' > .git/refs/remotes/origin/HEAD
./collab-context-collect.sh --role lead --repo example/equivalence --no-github --include shared.txt --out .dx/context.md >/dev/null
./collab-chat-start.sh --repo example/equivalence --no-github --include shared.txt --out .dx/start.dx.txt >/dev/null
python3 - <<'PY'
from pathlib import Path
import importlib.util
import json
spec = importlib.util.spec_from_file_location("collab_chat", "collab-chat.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
outer, _ = module.dx_parse(Path(".dx/start.dx.txt"))
state = json.loads(outer["repository-state.json"])
markdown = Path(".dx/context.md").read_text(encoding="utf-8")
assert f"Branch: {state['repository']['currentBranch']}" in markdown
assert f"HEAD: {state['repository']['head']}" in markdown
assert "### shared.txt" in markdown
inner_path = Path(".dx/repository-evidence.dx.txt")
inner_path.write_bytes(outer["repository-evidence.dx.txt"])
files, _ = module.dx_parse(inner_path)
assert set(files) == {"repository/shared.txt"}, set(files)
PY
printf 'PASS: Markdown and DX consumers expose equivalent repository facts\n'