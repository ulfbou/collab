#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HERE/collab-evidence.py" "$TMP/"
chmod +x "$TMP/collab-evidence.py"
cd "$TMP"; git init -q; git config user.name Test; git config user.email test@example.invalid; git remote add origin https://github.com/example/evidence.git
printf 'content\n' > file1.txt
printf 'binary\x00\x01\x02' > binary.bin
printf 'large content\n' > large.txt
git add .
git commit -qm init
mkdir -p out

# ---------------------------------------------------------------------------
# Test 1: GitHub Unavailable State
# ---------------------------------------------------------------------------
echo "Running Test: GitHub Unavailable"
mkdir -p "$TMP/mock_bin_fail"
cat << 'EOF' > "$TMP/mock_bin_fail/gh"
#!/bin/bash
exit 1
EOF
chmod +x "$TMP/mock_bin_fail/gh"
printf '@echo off\r\nexit /b 1\r\n' > "$TMP/mock_bin_fail/gh.bat"
printf '@echo off\r\nexit /b 1\r\n' > "$TMP/mock_bin_fail/gh.cmd"
export COLLAB_GH_BIN="$TMP/mock_bin_fail/gh"
python3 collab-evidence.py export-json --root "$TMP" --out-dir "$TMP/out"
if ! grep -q '"available": false' "$TMP/out/github-evidence.json"; then
  echo "FAIL: Expected GitHub to be explicitly unavailable."
  cat "$TMP/out/github-evidence.json"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 2: Partial GitHub Query Failure
# ---------------------------------------------------------------------------
echo "Running Test: Partial GitHub Query Failure"
mkdir -p "$TMP/mock_bin_partial"
cat << 'EOF' > "$TMP/mock_bin_partial/gh"
#!/bin/bash
if [[ "$1" == "auth" ]]; then exit 0; fi
if [[ "$1" == "pr" ]]; then echo "PR API Error" >&2; exit 1; fi
echo "[]"
EOF
chmod +x "$TMP/mock_bin_partial/gh"
printf '@echo off\r\nif "%%1"=="auth" exit /b 0\r\nif "%%1"=="pr" (\r\n  echo PR API Error 1>&2\r\n  exit /b 1\r\n)\r\necho []\r\nexit /b 0\r\n' > "$TMP/mock_bin_partial/gh.bat"
printf '@echo off\r\nif "%%1"=="auth" exit /b 0\r\nif "%%1"=="pr" (\r\n  echo PR API Error 1>&2\r\n  exit /b 1\r\n)\r\necho []\r\nexit /b 0\r\n' > "$TMP/mock_bin_partial/gh.cmd"
export COLLAB_GH_BIN="$TMP/mock_bin_partial/gh"
python3 collab-evidence.py export-json --root "$TMP" --out-dir "$TMP/out"
if ! grep -q '"openPullRequests": "failed"' "$TMP/out/github-evidence.json"; then
  echo "FAIL: Expected openPullRequests to explicitly register a failed query status."
  cat "$TMP/out/github-evidence.json"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 3: File Omissions & Limits
# ---------------------------------------------------------------------------
echo "Running Test: File Omissions"
python3 collab-evidence.py render-context \
  --root "$TMP" \
  --out "$TMP/out/context.md" \
  --max-bytes 10 \
  --include "file1.txt" \
  --include "missing.txt" \
  --include "binary.bin"
python3 collab-evidence.py export-json --root "$TMP" --out-dir "$TMP/out" --include "binary.bin" --include "large.txt" --include "missing.txt"
if ! grep -q '"status": "missing"' "$TMP/out/repository-facts.json"; then
  echo "FAIL: Missing files not explicitly reported."
  cat "$TMP/out/repository-facts.json"
  exit 1
fi
if ! grep -q '"status": "omitted_binary"' "$TMP/out/repository-facts.json"; then
  echo "FAIL: Binary files not identified and omitted."
  cat "$TMP/out/repository-facts.json"
  exit 1
fi

# ---------------------------------------------------------------------------
# Test 4: Atomic Writes & Symlink Safety
# ---------------------------------------------------------------------------
echo "Running Test: Symlink Rejection"
ln -s "$TMP/out/dummy" "$TMP/out/symlink.md"
if python3 collab-evidence.py render-context --root "$TMP" --out "$TMP/out/symlink.md" 2>/dev/null; then
  echo "FAIL: Collector allowed writing context to an unsafe symlink."
  exit 1
fi

echo "Collector Tests: PASS"