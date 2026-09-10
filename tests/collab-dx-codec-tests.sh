#!/usr/bin/env bash
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$HERE/.." && pwd -P)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/src/docs/private" "$TMP/src/code"
printf 'value' > "$TMP/src/plain.txt"
printf 'keep\n' > "$TMP/src/docs/keep.md"
printf 'secret\n' > "$TMP/src/docs/private/secret.md"
printf 'print(1)\n' > "$TMP/src/code/main.py"
printf '\377\000\376' > "$TMP/src/blob.bin"
printf '%s\n' '%%DX v1.3.1' '%%FILE path="a.txt"' 'x' '%%ENDBLOCK' '%%END' > "$TMP/src/nested.dx.txt"
python3 "$ROOT/dx.py" pack --root "$TMP/src" --out "$TMP/text.dx.txt" --include docs --include '*.py' --exclude docs/private
! grep -q 'secret.md' "$TMP/text.dx.txt"
grep -q 'docs/keep.md' "$TMP/text.dx.txt"
grep -q 'code/main.py' "$TMP/text.dx.txt"
python3 "$ROOT/dx.py" pack \
  --root "$TMP/src" \
  --out "$TMP/binary.dx.txt" \
  --path blob.bin
grep -q 'path="blob.bin" encoding="base64"' "$TMP/binary.dx.txt"

python3 "$ROOT/dx.py" pack \
  --root "$TMP/src" \
  --out "$TMP/skipped.dx.txt" \
  --path plain.txt \
  --path blob.bin \
  --skip-binary
grep -q 'path="plain.txt"' "$TMP/skipped.dx.txt"
! grep -q 'path="blob.bin"' "$TMP/skipped.dx.txt"

python3 "$ROOT/dx.py" pack \
  --root "$TMP/src" \
  --out "$TMP/all.dx.txt" \
  --path plain.txt \
  --path nested.dx.txt \
  --path blob.bin
grep -q 'path="blob.bin" encoding="base64"' "$TMP/all.dx.txt"
grep -q '^        %%DX v1.3.1$' "$TMP/all.dx.txt"
python3 "$ROOT/dx.py" apply "$TMP/all.dx.txt" "$TMP/out" --force
cmp "$TMP/src/plain.txt" "$TMP/out/plain.txt"
cmp "$TMP/src/blob.bin" "$TMP/out/blob.bin"
cmp "$TMP/src/nested.dx.txt" "$TMP/out/nested.dx.txt"
python3 "$ROOT/dx.py" inspect "$TMP/all.dx.txt" --compare-root "$TMP/out"
python3 "$ROOT/dx.py" inspect "$TMP/all.dx.txt" --hashes | grep -Fq "$(sha256sum "$TMP/src/blob.bin" | awk '{print $1}')  blob.bin"
printf 'PASS: canonical DX codec\n'

# Device defaults, naming, overwrite, help, and binary omission.
mkdir -p "$TMP/home/storage/downloads/DX" "$TMP/device/.git" "$TMP/device/.dx"
printf 'one\r\ntwo\r\n\r\n' > "$TMP/device/text.txt"
printf 'ignored\n' > "$TMP/device/.git/config"
printf 'ignored\n' > "$TMP/device/.dx/history.txt"
printf '\377\376' > "$TMP/device/binary.bin"
(
  cd "$TMP/device"
  HOME="$TMP/home" DX_DEVICE_DIR="$TMP/home/storage/downloads/DX" python3 "$ROOT/dx.py" pack > "$TMP/device-pack-1.out" 2> "$TMP/device-pack-1.err"
  HOME="$TMP/home" DX_DEVICE_DIR="$TMP/home/storage/downloads/DX" python3 "$ROOT/dx.py" pack > "$TMP/device-pack-2.out" 2> "$TMP/device-pack-2.err"
  HOME="$TMP/home" DX_DEVICE_DIR="$TMP/home/storage/downloads/DX" python3 "$ROOT/dx.py" pack --force > "$TMP/device-force.out" 2> "$TMP/device-force.err"
)
[[ -f "$TMP/home/storage/downloads/DX/dx-carrier-1.dx.txt" ]]
[[ -f "$TMP/home/storage/downloads/DX/dx-carrier-2.dx.txt" ]]
[[ -f "$TMP/home/storage/downloads/DX/dx-carrier-3.dx.txt" ]]
! grep -q '.git/config' "$TMP/home/storage/downloads/DX/dx-carrier-1.dx.txt"
! grep -q '.dx/history.txt' "$TMP/home/storage/downloads/DX/dx-carrier-1.dx.txt"
grep -q 'path="binary.bin" encoding="base64"' "$TMP/home/storage/downloads/DX/dx-carrier-1.dx.txt"
grep -q 'Skipped non-UTF-8: 0 files' "$TMP/device-pack-1.err"
python3 "$ROOT/dx.py" -h | grep -q 'DX v2.0.0 carrier utility'
python3 "$ROOT/dx.py" pack -h >/dev/null
python3 "$ROOT/dx.py" unpack -h >/dev/null
python3 "$ROOT/dx.py" apply -h >/dev/null
python3 "$ROOT/dx.py" inspect -h >/dev/null
if python3 "$ROOT/dx.py" pack "$TMP/device" "$TMP/home/storage/downloads/DX/dx-carrier-1.dx.txt" >/dev/null 2>&1; then
  echo 'ERROR: explicit existing output was replaced without --force' >&2; exit 1
fi
printf 'PASS: device DX defaults and help\n'
