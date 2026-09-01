#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh"; require_executed
require_cmd git; root=$(repo_root); cd "$root"
mapfile -t sln < <(find . -maxdepth 2 -type f \( -name '*.slnx' -o -name '*.sln' \) ! -path '*/bin/*' ! -path '*/obj/*' | sort)
((${#sln[@]} <= 1)) || die "expected at most one solution file, found ${#sln[@]}"
if ((${#sln[@]} == 1)); then
  require_cmd dotnet
  phase 'BUILD'
  dotnet build "${sln[0]}"
  phase 'TEST'
  dotnet test "${sln[0]}" --no-build
fi
if [[ -x scripts/verify-verdant.sh ]]; then phase 'REPOSITORY VERIFICATION'; bash scripts/verify-verdant.sh; fi
printf '\nVerification passed for HEAD %s\n' "$(git rev-parse HEAD)"
