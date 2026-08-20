#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export COLLAB_SOURCE_ROOT="$HERE"

cd "$TMP"
git init -q
printf '/.dx/\n' >> .git/info/exclude
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/ulfbou/mock-repo.git

printf 'shared\n' > shared.txt
git add shared.txt
git commit -qm init
git branch -M main

"$HERE/collab-context-collect.sh" \
  --role lead \
  --repo ulfbou/mock-repo \
  --no-github \
  --include shared.txt \
  --out .dx/context.md >/dev/null

"$HERE/collab-chat-start.sh" \
  --repo ulfbou/mock-repo \
  --no-github \
  --include shared.txt \
  --out .dx/start.dx.txt >/dev/null

python3 - <<'PY'
from pathlib import Path
import importlib.util
import json
import os

spec = importlib.util.spec_from_file_location(
    "collab_chat",
    os.path.join(
        os.environ["COLLAB_SOURCE_ROOT"],
        "collab-chat.py",
    ),
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

outer, _ = module.dx_parse(
    Path(".dx/start.dx.txt")
)
state = json.loads(
    outer["repository-state.json"]
)
markdown = Path(".dx/context.md").read_text(
    encoding="utf-8"
)

repository = state["repository"]

assert (
    f"- Repository: `{repository['nameWithOwner']}`"
    in markdown
), markdown

assert (
    f"- Current branch: `{repository['currentBranch']}`"
    in markdown
), markdown

assert (
    f"- HEAD: `{repository['head']}`"
    in markdown
), markdown

assert (
    f"- Working tree: `{repository['workingTree']}`"
    in markdown
), markdown

assert "- `shared.txt`: `included`" in markdown, markdown

inner_path = Path(
    ".dx/repository-evidence.dx.txt"
)
inner_path.write_bytes(
    outer["repository-evidence.dx.txt"]
)

files, _ = module.dx_parse(inner_path)
inner_path.unlink()

assert set(files) == {
    "repository/shared.txt",
}, set(files)
PY

printf 'PASS: Markdown and DX consumers expose equivalent repository facts\n'
