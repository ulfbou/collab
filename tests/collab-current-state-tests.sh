#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
export COLLAB_REPO_ROOT="$HERE"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"

python3 - <<'PY'
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

root = Path(os.environ["COLLAB_REPO_ROOT"])
spec = importlib.util.spec_from_file_location("collab_evidence", root / "collab-evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

schema = json.loads((root / "schemas" / "current-state.schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(schema)


def make_model(*, requested=True, available=True, selected_issue_requested=True, selected_issue_present=True, reverse_order=False):
    repository = {
        "nameWithOwner": "ulfbou/collab",
        "defaultBranchRef": {"name": "main"},
    }
    if reverse_order:
        repository = {
            "defaultBranchRef": {"name": "main"},
            "nameWithOwner": "ulfbou/collab",
        }

    issue = {
        "number": 61,
        "title": "architecture: establish Current State Record and semantic identity",
        "state": "OPEN",
        "labels": [{"name": "priority:foundation"}],
        "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
        "assignees": [{"login": "ulfbou"}],
        "url": "https://example.invalid/issues/61",
    }
    if reverse_order:
        issue = {
            "url": "https://example.invalid/issues/61",
            "assignees": [{"login": "ulfbou"}],
            "milestone": {"title": "Collab: boundary-centric collaboration model", "number": 1},
            "labels": [{"name": "priority:foundation"}],
            "state": "OPEN",
            "title": "architecture: establish Current State Record and semantic identity",
            "number": 61,
        }

    data = {
        "repository": repository,
        "openIssues": [
            {
                "number": 61,
                "state": "OPEN",
                "title": "Issue 61",
                "labels": [{"name": "priority:foundation"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "url": "https://example.invalid/open-issue",
            },
            {
                "number": 62,
                "state": "OPEN",
                "title": "Issue 62",
                "labels": [{"name": "type:contracts"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "url": "https://example.invalid/open-issue-62",
            },
        ],
        "openPullRequests": [
            {
                "number": 83,
                "state": "OPEN",
                "title": "Architecture",
                "baseRefName": "main",
                "headRefName": "feat/current-state-record",
                "headRefOid": "0123456789abcdef0123456789abcdef01234567",
                "labels": [{"name": "type:architecture"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "author": {"login": "ulfbou"},
                "url": "https://example.invalid/pr/83",
            },
            {
                "number": 84,
                "state": "OPEN",
                "title": "Architecture follow-up",
                "baseRefName": "main",
                "headRefName": "feat/current-state-record-2",
                "headRefOid": "fedcba9876543210fedcba9876543210fedcba98",
                "labels": [{"name": "type:architecture"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "author": {"login": "ulfbou"},
                "url": "https://example.invalid/pr/84",
            },
        ],
        "recentlyMergedPullRequests": [
            {
                "number": 83,
                "state": "MERGED",
                "title": "Architecture",
                "baseRefName": "main",
                "headRefName": "feat/current-state-record",
                "headRefOid": "0123456789abcdef0123456789abcdef01234567",
                "mergeCommit": {"oid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
                "mergedAt": "2026-10-16T00:00:00Z",
                "labels": [{"name": "type:architecture"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "author": {"login": "ulfbou"},
                "url": "https://example.invalid/pr/83",
            },
            {
                "number": 84,
                "state": "MERGED",
                "title": "Architecture follow-up",
                "baseRefName": "main",
                "headRefName": "feat/current-state-record-2",
                "headRefOid": "fedcba9876543210fedcba9876543210fedcba98",
                "mergeCommit": {"oid": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
                "mergedAt": "2026-10-17T00:00:00Z",
                "labels": [{"name": "type:architecture"}],
                "milestone": {"number": 1, "title": "Collab: boundary-centric collaboration model"},
                "author": {"login": "ulfbou"},
                "url": "https://example.invalid/pr/84",
            },
        ],
        "labels": [{"name": "priority:foundation", "color": "D93F0B"}],
        "milestones": [{"number": 1, "title": "Collab: boundary-centric collaboration model", "state": "OPEN"}],
    }
    if reverse_order:
        data = {
            "milestones": [{"state": "OPEN", "title": "Collab: boundary-centric collaboration model", "number": 1}],
            "labels": [{"color": "D93F0B", "name": "priority:foundation"}],
            "recentlyMergedPullRequests": list(reversed(data["recentlyMergedPullRequests"])),
            "openPullRequests": list(reversed(data["openPullRequests"])),
            "openIssues": list(reversed(data["openIssues"])),
            "repository": repository,
        }

    query_status = {
        "repository": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
        "openIssues": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
        "openPullRequests": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
        "recentlyMergedPullRequests": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
        "labels": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
        "milestones": "ok" if requested and available else ("unavailable" if requested and not available else "not_requested"),
    }
    if selected_issue_requested:
        query_status["selectedIssue"] = "ok" if selected_issue_present and requested and available else ("failed" if requested and available else "unavailable")
    else:
        query_status["selectedIssue"] = "not_applicable"

    selected_issue = issue if selected_issue_requested and selected_issue_present else None
    errors = []
    if requested and not available:
        errors.append({"section": "authentication", "error": "github unavailable"})
    if selected_issue_requested and not selected_issue_present and requested and available:
        errors.append({"section": "selectedIssue", "error": "selected issue lookup failed"})

    if not requested:
        data = {}
        selected_issue = None
        errors = []
        query_status = {}

    github = {
        "schemaVersion": "1.0",
        "repository": "ulfbou/collab",
        "requested": requested,
        "available": available,
        "selectedIssueRequested": selected_issue_requested,
        "queryStatus": query_status,
        "errors": errors,
        "data": data,
        "selectedIssue": selected_issue,
    }
    if reverse_order:
        github = {
            "selectedIssue": selected_issue,
            "data": data,
            "errors": errors,
            "queryStatus": query_status,
            "selectedIssueRequested": selected_issue_requested,
            "available": available,
            "requested": requested,
            "repository": "ulfbou/collab",
            "schemaVersion": "1.0",
        }

    configuration = {
        "includes": ["README.md"],
        "excludes": [".dx"],
        "maxBytes": 262144,
        "recentCommits": 20,
        "github": requested,
        "consumerRoot": None,
        "consumerIncludes": [],
        "withFiles": True,
        "selectedIssue": 61 if selected_issue_requested else None,
        "recentClosed": 20,
    }
    if reverse_order:
        configuration = {
            "recentClosed": 20,
            "selectedIssue": 61 if selected_issue_requested else None,
            "withFiles": True,
            "consumerIncludes": [],
            "consumerRoot": None,
            "github": requested,
            "recentCommits": 20,
            "maxBytes": 262144,
            "excludes": [".dx"],
            "includes": ["README.md"],
        }

    selected_files = [
        {
            "path": "README.md",
            "size": 1,
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "status": "included",
            "content": "x",
        }
    ]

    if reverse_order:
        selected_files = [dict(reversed(list(selected_files[0].items())))]

    return {
        "generatedAt": "2026-10-16T00:00:00Z",
        "git": {
            "repository": "ulfbou/collab",
            "origin": "https://github.com/ulfbou/collab.git",
            "root": str(root),
            "defaultBranch": "main",
            "currentBranch": "feat/current-state-record",
            "head": "0123456789abcdef0123456789abcdef01234567",
            "workingTree": "CLEAN",
            "statusPorcelain": "",
            "trackedTree": ["README.md"],
            "recentCommits": [
                {
                    "sha": "0123456789abcdef0123456789abcdef01234567",
                    "date": "2026-10-15T00:00:00Z",
                    "subject": "init",
                }
            ],
        },
        "github": github,
        "selectedFiles": selected_files,
        "relationships": {
            "providers": [{"kind": "issue", "id": "61"}],
            "consumers": [{"kind": "pull_request", "id": "83"}],
        },
        "configuration": configuration,
    }


def capture_state(cwd: Path):
    return {
        "branch": subprocess.run(["git", "branch", "--show-current"], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
        "status": subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE).stdout,
    }


def assert_valid(record):
    validator.validate(record)


def assert_invalid(record, needle):
    try:
        validator.validate(record)
    except Exception as exc:  # noqa: BLE001
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f"expected validation failure containing {needle!r}")


base = make_model()
record_a = module.current_state_record(copy.deepcopy(base), capture_id="capture:20261017T000000.000000Z-aaaa1111", output_path="out/one.json", rendering={"columns": ["a", "b"], "order": 1})
record_b = module.current_state_record(copy.deepcopy(base), capture_id="capture:20261017T000001.000000Z-bbbb2222", output_path="out/two.json", rendering={"order": 1, "columns": ["a", "b"]})
assert record_a["captureId"] != record_b["captureId"]
assert record_a["stateIdentity"] == record_b["stateIdentity"]
assert record_a["stateIdentity"].startswith("sha256:v1:")

same_timestamp = copy.deepcopy(base)
same_timestamp["generatedAt"] = "2026-10-16T12:34:56Z"
assert module.current_state_record(copy.deepcopy(same_timestamp), capture_id="capture:20261017T000002.000000Z-cccc3333")["stateIdentity"] == record_a["stateIdentity"]

reordered = make_model(reverse_order=True)
assert module.current_state_record(copy.deepcopy(reordered), capture_id="capture:20261017T000003.000000Z-dddd4444")["stateIdentity"] == record_a["stateIdentity"]

incidental = copy.deepcopy(base)
incidental["github"]["errors"] = [{"section": "selectedIssue", "error": "different diagnostic text"}]
incidental["github"]["data"]["repository"]["url"] = "https://example.invalid/other-repo-url"
incidental["github"]["data"]["openIssues"][0]["url"] = "https://example.invalid/other-open-issue"
assert module.current_state_record(copy.deepcopy(incidental), capture_id="capture:20261017T000004.000000Z-eeee5555")["stateIdentity"] == record_a["stateIdentity"]

changed_control = copy.deepcopy(base)
changed_control["git"]["head"] = "ffffffffffffffffffffffffffffffffffffffff"
assert module.current_state_record(changed_control)["stateIdentity"] != record_a["stateIdentity"]

changed_hosted = copy.deepcopy(base)
changed_hosted["github"]["data"]["openIssues"][0]["title"] = "changed"
assert module.current_state_record(changed_hosted)["stateIdentity"] != record_a["stateIdentity"]

changed_candidate = copy.deepcopy(base)
changed_candidate["github"]["selectedIssue"]["title"] = "changed"
assert module.current_state_record(changed_candidate)["stateIdentity"] != record_a["stateIdentity"]

changed_configuration = copy.deepcopy(base)
changed_configuration["configuration"]["maxBytes"] = 1
assert module.current_state_record(changed_configuration)["stateIdentity"] != record_a["stateIdentity"]

assert_valid(record_a)
assert_invalid({**record_a, "captureId": "bad"}, "captureId")
bad_classification = copy.deepcopy(record_a)
bad_classification["classifications"]["workingTree"]["evidence"] = "nope"
assert_invalid(bad_classification, "evidence")
bad_completeness = copy.deepcopy(record_a)
bad_completeness["completeness"]["hosted"]["domains"]["openIssues"]["status"] = "broken"
assert_invalid(bad_completeness, "openIssues")
bad_mutation = copy.deepcopy(record_a)
bad_mutation["verification"]["mutationSentinel"]["prohibitedSurfaces"] = "nope"
assert_invalid(bad_mutation, "prohibitedSurfaces")

compat_from_model = module.repository_state(copy.deepcopy(base))
compat_from_record = module.repository_state(copy.deepcopy(record_a))
assert compat_from_model == compat_from_record
compat_snapshot = copy.deepcopy(record_a)
assert module.repository_state(record_a) == compat_from_model
assert record_a == compat_snapshot

assert record_a["verification"]["mutationSentinel"] == {
    "contractVersion": "1",
    "operation": "current-state-capture-and-projection",
    "evidenceType": "test-evidence",
    "prohibitedSurfaces": [
        "tracked-content",
        "index",
        "working-tree",
        "branch",
        "HEAD",
        "hosted-state",
        "accepted-history",
    ],
    "unmeasuredSurfaces": ["live-telemetry"],
    "limitations": [
        "non-mutation is established by implementation contract and focused tests, not by embedded runtime telemetry",
    ],
}

assert record_a["classifications"]["workingTree"] == {
    "value": "CLEAN",
    "evidence": ["observations.git.statusPorcelain", "observations.git.workingTree"],
    "rule": {"id": "working-tree-classification", "version": "1"},
}
assert record_a["classifications"]["hostedState"]["value"] == "available"
assert record_a["classifications"]["selectedIssue"]["value"] == "observed"

hosted = record_a["completeness"]["hosted"]
assert hosted["overall"] == "observed"
assert hosted["domains"]["openIssues"]["status"] == "observed"
assert hosted["domains"]["selectedIssue"]["status"] == "observed"

not_requested = module.current_state_record(make_model(requested=False, available=False, selected_issue_requested=False, selected_issue_present=False), capture_id="capture:20261017T000005.000000Z-ffff6666")
assert not_requested["completeness"]["hosted"]["overall"] == "not_requested"
assert {entry["status"] for entry in not_requested["completeness"]["hosted"]["domains"].values()} == {"not_requested"}
assert not_requested["classifications"]["hostedState"]["value"] == "not_requested"

not_applicable = module.current_state_record(make_model(selected_issue_requested=False), capture_id="capture:20261017T000006.000000Z-11117777")
assert not_applicable["completeness"]["hosted"]["overall"] == "observed"
assert not_applicable["classifications"]["hostedState"]["value"] == "available"
assert not_applicable["completeness"]["hosted"]["domains"]["selectedIssue"]["status"] == "not_applicable"

unavailable = module.current_state_record(make_model(requested=True, available=False, selected_issue_requested=True, selected_issue_present=False), capture_id="capture:20261017T000007.000000Z-22228888")
assert unavailable["completeness"]["hosted"]["overall"] == "unavailable"
assert unavailable["completeness"]["hosted"]["domains"]["openIssues"]["status"] == "unavailable"
assert unavailable["classifications"]["hostedState"]["value"] == "unavailable"

partial = copy.deepcopy(base)
partial["github"]["queryStatus"]["openPullRequests"] = "failed"
partial["github"]["errors"].append({"section": "openPullRequests", "error": "boom"})
partial_record = module.current_state_record(partial, capture_id="capture:20261017T000008.000000Z-33339999")
assert partial_record["completeness"]["hosted"]["domains"]["openPullRequests"]["status"] == "failed"
assert partial_record["completeness"]["hosted"]["domains"]["openIssues"]["status"] == "observed"
assert partial_record["completeness"]["hosted"]["overall"] == "partial"
assert partial_record["consistency"]["conflicts"] == []
assert partial_record["limitations"]

selected_issue_failure = copy.deepcopy(base)
selected_issue_failure["github"]["queryStatus"]["selectedIssue"] = "failed"
selected_issue_failure["github"]["selectedIssue"] = None
selected_issue_failure["github"]["errors"].append({"section": "selectedIssue", "error": "selected issue lookup failed"})
selected_issue_failure_record = module.current_state_record(selected_issue_failure, capture_id="capture:20261017T000009.000000Z-4444aaaa")
assert selected_issue_failure_record["completeness"]["hosted"]["domains"]["selectedIssue"]["status"] == "failed"
assert selected_issue_failure_record["classifications"]["selectedIssue"]["value"] == "failed"
assert selected_issue_failure_record["consistency"]["conflicts"] == []

with tempfile.TemporaryDirectory() as d:
    repo = Path(d)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    before = capture_state(repo)
    snapshot = copy.deepcopy(base)
    snapshot_copy = copy.deepcopy(snapshot)
    identity_record = module.current_state_record(snapshot, capture_id="capture:20261017T000010.000000Z-5555bbbb", output_path="output.json", rendering={"z": 1, "a": 2})
    identity_snapshot = copy.deepcopy(identity_record)
    compatibility_record = module.repository_state(identity_record)
    after = capture_state(repo)

    assert snapshot == snapshot_copy
    assert before == after
    assert identity_record == identity_snapshot
    assert compatibility_record == module.repository_state(copy.deepcopy(base))
    assert compatibility_record == module.repository_state(identity_record)

print("PASS: current-state identity, projection, schema, and mutation sentinel")
PY
