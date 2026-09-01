#!/usr/bin/env bash
set -Eeuo pipefail
REPO=ulfbou/mock-repo; BASE=test-base
verify_access(){ gh auth status >/dev/null;[[ $(gh repo view "$REPO" --json nameWithOwner --jq .nameWithOwner)=="$REPO" ]];[[ $(gh api "repos/$REPO" --jq .permissions.push)==true ]];gh api "repos/$REPO/git/ref/heads/$BASE" >/dev/null; }
verify_access;NOW=$(date -u +%s);bad=0
while read -r b;do [[ $b == test/evidence/* ]]||continue;stamp=$(cut -d/ -f4<<<"$b");if [[ ! $stamp =~ ^([0-9]{8}T[0-9]{6}Z)-[0-9]+-[0-9a-f]{8}$ ]];then echo "SKIP malformed: $b";continue;fi;ts=$(date -u -d "${BASH_REMATCH[1]:0:8} ${BASH_REMATCH[1]:9:2}:${BASH_REMATCH[1]:11:2}:${BASH_REMATCH[1]:13:2}" +%s 2>/dev/null)||{ echo "SKIP invalid: $b";continue;};((NOW-ts>172800))&&gh api -X DELETE "repos/$REPO/git/refs/heads/$b"||true;done < <(gh api --paginate "repos/$REPO/branches?per_page=100" --jq '.[].name')
