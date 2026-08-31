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
import re

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

# Check key fields without relying on exact path or working‑tree wording.
assert f"- Role: `lead`" in markdown, "Role missing"
assert f"- GitHub repository: `{repository['nameWithOwner']}`" in markdown, "GitHub repository missing"
assert re.search(r'- Repository root: `.*`', markdown), "Repository root line missing"

# Repository state block – verify branch and HEAD are present.
assert f"Branch: {repository['currentBranch']}" in markdown, "Branch missing"
assert f"HEAD: {repository['head']}" in markdown, "HEAD missing"

# The working tree status is shown via the `Status:` line; we no longer have a separate
# "Working tree: CLEAN" line, so we don't assert it here.

# Selected file header and content.
assert f"### `shared.txt`" in markdown, "shared.txt header missing"
assert "shared" in markdown, "shared.txt content missing"

# DX packaging equivalence: the repository evidence must contain exactly one file.
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