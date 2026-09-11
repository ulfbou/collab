#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cp "$HERE/collab-delivery-run.sh" "$HERE/collab-dx-inspect.sh" "$HERE/collab-dx-apply-checked.sh" "$HERE/collab-dx-pack.py" "$HERE/collab-state.py" "$HERE/lib-common.sh" "$HERE/collab-artifact-publish.sh" "$HERE/dx.py" "$TMP/"
cp -R "$HERE/collab" "$TMP/"
cd "$TMP"

chmod +x collab-delivery-run.sh collab-dx-inspect.sh collab-dx-apply-checked.sh collab-dx-pack.py collab-state.py dx.py

git init -q
git config user.name Test
git config user.email test@example.invalid
git remote add origin https://github.com/example/recovery.git

printf 'before\n' > tracked.txt
git add tracked.txt
git commit -qm baseline
git branch -M main
git update-ref refs/remotes/origin/main HEAD
git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
git switch -qc fix/windows-dx-delivery-recovery
printf 'after\n' > tracked.txt

printf 'provider\n' > provider.slnx
mkdir -p consumer
printf 'consumer\n' > consumer/consumer.slnx

cat > collab-repo-state.sh <<'EOF'
#!/usr/bin/env bash
printf 'repo-state\n'
EOF
cat > collab-git-change-audit.sh <<'EOF'
#!/usr/bin/env bash
printf 'audit\n'
EOF
cat > collab-work-verify.sh <<'EOF'
#!/usr/bin/env bash
printf 'verify\n'
EOF
chmod +x collab-repo-state.sh collab-git-change-audit.sh collab-work-verify.sh

mkdir -p bin
cat > bin/dotnet <<'EOF'
#!/usr/bin/env bash
printf 'dotnet %s\n' "$*" >> "$CALL_LOG"
exit 0
EOF
chmod +x bin/dotnet
export PATH="$TMP/bin:$PATH" CALL_LOG="$TMP/calls.log"

python3 collab-state.py save delivery --json '{"issue":"18","branch":"fix/windows-dx-delivery-recovery","title":"Recovery","carrier":"carrier.dx.txt","providerSolution":"provider.slnx","consumerRoot":"consumer","consumerSolution":"consumer/consumer.slnx","toolsDir":"/f/scripts","outputPrefix":"delivery","skipApply":false,"allows":["old-allow","old-allow","legacy-allow"],"focusedTests":["old-test","old-test"],"auditScopes":["old-scope","old-scope"]}'
python3 dx.py pack --root . --out carrier.dx.txt --path tracked.txt

if ! bash ./collab-delivery-run.sh \
  --issue 18 \
  --branch fix/windows-dx-delivery-recovery \
  --title Recovery \
  --carrier carrier.dx.txt \
  --provider-solution provider.slnx \
  --consumer-root consumer \
  --consumer-solution consumer.slnx \
  --tools-dir "$TMP" \
  --allow tracked.txt \
  --allow tracked.txt \
  --focused-test tests/placeholder \
  --focused-test tests/placeholder \
  --audit-scope tracked.txt \
  --audit-scope tracked.txt \
  --skip-apply >"$TMP/delivery-run.out" 2>&1
then
  printf 'FAIL: delivery workflow failed\n' >&2
  cat "$TMP/delivery-run.out" >&2

  if [[ -f .dx/delivery-run/master.log ]]; then
    printf '\n=== delivery master log ===\n' >&2
    cat .dx/delivery-run/master.log >&2
  fi

  if [[ -f .dx/delivery-failure-report.txt ]]; then
    printf '\n=== delivery failure report ===\n' >&2
    cat .dx/delivery-failure-report.txt >&2
  fi

  false
fi

python3 - <<'PY'
import json
from pathlib import Path

document = json.loads(Path('.dx/collab/profiles/delivery.json').read_text(encoding='utf-8'))
values = document['values']
assert values['toolsDir'] != '/f/scripts', values['toolsDir']
assert values['allows'] == ['tracked.txt'], values['allows']
assert values['focusedTests'] == ['tests/placeholder'], values['focusedTests']
assert values['auditScopes'] == ['tracked.txt'], values['auditScopes']
PY

bash ./collab-dx-inspect.sh .dx/delivery-final.dx.txt --compare-root .
bash ./collab-dx-inspect.sh .dx/delivery-final.dx.txt --list | tr -d '\r' | grep -Fqx -- 'tracked.txt'

printf 'PASS: delivery recovery defaults, replacement, dedup, and skip-apply equivalence\n'

record=$(find .dx/collab/runs -name run.json -type f | sort | tail -1)
jq -e '.status=="success" and (.artifacts|length)==3 and all(.artifacts[]; .immutablePath|type=="string")' "$record" >/dev/null
grep -F 'Files to upload (run ' .dx/delivery-upload-manifest.txt >/dev/null
for file in .dx/delivery-final.dx.txt .dx/delivery-delivery-evidence.txt .dx/delivery-delivery-report.txt; do [[ -f $file ]]; grep -F "$file" .dx/delivery-upload-manifest.txt >/dev/null; done
printf 'PASS: delivery advertises stable immutable-backed artifacts
'
