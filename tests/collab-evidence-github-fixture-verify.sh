#!/usr/bin/env bash
set -Eeuo pipefail
REPO=ulfbou/mock-repo; BASE=test-base
verify_access(){ gh auth status >/dev/null;[[ $(gh repo view "$REPO" --json nameWithOwner --jq .nameWithOwner)=="$REPO" ]];[[ $(gh api "repos/$REPO" --jq .permissions.push)==true ]];gh api "repos/$REPO/git/ref/heads/$BASE" >/dev/null; }
verify_access
[[ $(gh issue list --repo "$REPO" --state open --limit 100 --json title,body --jq '.[]|select(.title=="[collab-fixture] Available issue" and (.body|length)>0)|.title') ]]
m=$(gh api "repos/$REPO/milestones?state=open");jq -e '.[]|select(.title=="[collab-fixture] Milestone" and (.description|length)>0 and .due_on!=null)'<<<"$m">/dev/null
for l in collab-fixture-open collab-fixture-milestone;do gh label list --repo "$REPO" --limit 100 --json name --jq '.[].name'|grep -Fxq "$l";done
gh pr list --repo "$REPO" --state merged --limit 100 --json title --jq '.[].title'|grep -Fxq '[collab-fixture] Recently merged PR';echo 'PASS: permanent GitHub fixtures verified'
