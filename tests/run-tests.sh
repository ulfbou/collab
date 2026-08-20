#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

shopt -s nullglob
tests=("$HERE"/collab-*-tests.sh)
shopt -u nullglob

((${#tests[@]} > 0)) || {
  printf 'ERROR: no test scripts matched tests/*-tests.sh\n' >&2
  exit 1
}

failures=()

for test in "${tests[@]}"; do
  name=${test#"$HERE/"}
  printf '=== tests/%s ===\n' "$name"

  if ! bash "$test"; then
    failures+=("tests/$name")
  fi
done

printf '\n'

if ((${#failures[@]} > 0)); then
  printf 'FAILED TESTS (%d):\n' "${#failures[@]}" >&2
  printf -- '- %s\n' "${failures[@]}" >&2
  exit 1
fi

printf 'ALL TESTS PASSED (%d scripts)\n' "${#tests[@]}"
