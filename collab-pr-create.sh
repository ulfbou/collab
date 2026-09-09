#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$SCRIPT_DIR/lib-common.sh";require_executed
require_cmd jq;require_cmd git;require_cmd gh
root=$(repo_root);cd "$root";repo=$(origin_repo);default=$(default_branch);branch=$(git branch --show-current)
p=$(collab_profile_json pr);d=$(collab_profile_json delivery)
issue=$(jq -r '.issue // empty'<<<"$p");[[ -n $issue ]]||issue=$(jq -r '.issue // empty'<<<"$d");title=$(jq -r '.title // empty'<<<"$p");[[ -n $title ]]||title=$(jq -r '.title // empty'<<<"$d")
body='';body_file=$(jq -r '.bodyFile // empty'<<<"$p");draft=$(jq -r '.draft // false'<<<"$p");milestone=$(jq -r '.milestone // empty'<<<"$p");inherit=$(jq -r '.inheritMilestone // true'<<<"$p");base=$(jq -r '.base // empty'<<<"$p");[[ -n $base ]]||base=$default;dry=false
mapfile -t assignees < <(jq -r '.assignees[]?'<<<"$p");((${#assignees[@]}))||assignees=('@me');mapfile -t labels < <(jq -r '.labels[]?'<<<"$p");mapfile -t reviewers < <(jq -r '.reviewers[]?'<<<"$p");mapfile -t teams < <(jq -r '.teamReviewers[]?'<<<"$p")
a_seen=0;l_seen=0;r_seen=0;t_seen=0
while (($#));do case "$1" in
 --issue) shift;issue=${1:?};;--title) shift;title=${1:?};;--body) shift;body=${1:?};;--body-file) shift;body_file=${1:?};;--base) shift;base=${1:?};;
 --assignee) shift;((a_seen++))||assignees=("@me");assignees+=("$1");;--no-assignee) a_seen=1;assignees=();;
 --label) shift;((l_seen++))||labels=();labels+=("$1");;--clear-labels) l_seen=1;labels=();;
 --reviewer) shift;((r_seen++))||reviewers=();reviewers+=("$1");;--clear-reviewers) r_seen=1;reviewers=();;
 --team-reviewer) shift;((t_seen++))||teams=();teams+=("$1");;--clear-team-reviewers) t_seen=1;teams=();;
 --milestone) shift;milestone=${1:?};inherit=false;;--no-milestone) milestone='';inherit=false;;--draft)draft=true;;--ready)draft=false;;--dry-run)dry=true;;
 -h|--help) echo 'Usage: collab-pr-create.sh [--issue N] [--base BRANCH] [--title T] [--body B|--body-file F] [--assignee U|--no-assignee] [--label L] [--reviewer U] [--team-reviewer T] [--milestone M|--no-milestone] [--draft|--ready] [--dry-run]';exit 0 # --base BRANCH: Target branch for PR (defaults to repository default);;*)usage_error "unknown argument: $1";;esac;shift;done
[[ -n $base && $base != "$default" ]] && { branch_exists "$base" || die "base branch does not exist: $base"; }
[[ $issue =~ ^[0-9]+$ ]]||usage_error '--issue must be numeric';[[ -n $title ]]||usage_error '--title is required';[[ -z $body||-z $body_file ]]||usage_error '--body and --body-file are mutually exclusive'
phase PREFLIGHT;[[ -n $branch&&$branch != "$default" ]]||die 'PR creation requires a non-default branch';gh auth status>/dev/null 2>&1||die 'gh authentication unavailable'
existing=$(gh pr list --repo "$repo" --head "$branch" --state open --json number,url);[[ $(jq length<<<"$existing")==0 ]]||die "an open PR already exists for branch $branch"
issue_json=$(gh issue view "$issue" --repo "$repo" --json state,labels,milestone);[[ $(jq -r .state<<<"$issue_json")==OPEN ]]||die "issue #$issue is not open"
[[ -z $(git diff --name-only) ]]||die 'unstaged changes must be staged or reverted';[[ -z $(git ls-files --others --exclude-standard) ]]||die 'untracked files must be staged, ignored, or removed'
[[ -z $body_file ]]||{ [[ -f $body_file ]]||die "body file not found: $body_file";body=$(cat -- "$body_file");};[[ -n $body ]]||body=$'Closes #'"$issue"$'\n\n## Summary\n\nImplements the bounded delivery.\n\n## Verification\n\n- Local verification completed successfully.\n'
grep -Eq "(^|[[:space:]])(Closes|Fixes|Resolves)[[:space:]]+#${issue}([^0-9]|$)"<<<"$body"||die "PR body must close issue #$issue";grep -q '^## Summary$'<<<"$body"||die 'PR body requires ## Summary';grep -q '^## Verification$'<<<"$body"||die 'PR body requires ## Verification';grep -Eqi 'TODO|TBD|PLACEHOLDER'<<<"$body"&&die 'PR body contains a placeholder'
mapfile -t inherited < <(jq -r '.labels[].name'<<<"$issue_json");labels+=("${inherited[@]}");mapfile -t labels < <(printf '%s\n' "${labels[@]}"|awk 'NF&&!x[$0]++');$inherit&&[[ -z $milestone ]]&&milestone=$(jq -r '.milestone.title//empty'<<<"$issue_json")
printf 'Repository: %s\nBranch: %s\nBase: %s\nIssue: %s\nTitle: %s\nAssignees: %s\nLabels: %s\nMilestone: %s\n' "$repo" "$branch" "$base" "$issue" "$title" "${assignees[*]:-none}" "${labels[*]:-none}" "${milestone:-none}"
$dry&&exit 0
"$SCRIPT_DIR/collab-work-verify.sh";phase COMMIT;if ! git diff --cached --quiet;then git commit -m "$title";fi;clean_tree||die 'tree not clean after commit';git push -u origin "$branch"
args=(pr create --repo "$repo" --base "$base" --head "$branch" --title "$title" --body "$body");$draft&&args+=(--draft);for x in "${assignees[@]}";do args+=(--assignee "$x");done;for x in "${labels[@]}";do args+=(--label "$x");done;for x in "${reviewers[@]}" "${teams[@]}";do [[ -z $x ]]||args+=(--reviewer "$x");done;[[ -z $milestone ]]||args+=(--milestone "$milestone")
url=$(gh "${args[@]}");data=$(gh pr view "$url" --repo "$repo" --json number,url,headRefOid);n=$(jq -r .number<<<"$data");head=$(jq -r .headRefOid<<<"$data")
json=$(jq -cn --arg issue "$issue" --arg title "$title" --arg bf "$body_file" --argjson draft "$draft" --argjson aa "$(printf '%s\n' "${assignees[@]}"|jq -Rsc 'split("\n")[:-1]')" --argjson ll "$(printf '%s\n' "${labels[@]}"|jq -Rsc 'split("\n")[:-1]')" --argjson rr "$(printf '%s\n' "${reviewers[@]}"|jq -Rsc 'split("\n")[:-1]')" --argjson tt "$(printf '%s\n' "${teams[@]}"|jq -Rsc 'split("\n")[:-1]')" --arg ms "$milestone" --argjson inh "$inherit" --argjson pn "$n" --arg u "$url" --arg b "$branch" --arg base "$base" --arg h "$head" --arg repo "$repo" '{issue:$issue,base:$base,title:$title,bodyFile:$bf,draft:$draft,assignees:$aa,labels:$ll,reviewers:$rr,teamReviewers:$tt,milestone:$ms,inheritMilestone:$inh,prNumber:$pn,prUrl:$u,branch:$b,head:$h,repository:$repo}')
collab_profile_save_json pr "$json";jq .<<<"$data"