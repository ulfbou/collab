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

root = Path(os.environ["COLLAB_REPO_ROOT"])
spec = importlib.util.spec_from_file_location("collab_evidence", root / "collab-evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

schema = json.loads((root / "schemas" / "current-state.schema.json").read_text(encoding="utf-8"))


def base_model():
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
        "github": {
            "schemaVersion": "1.0",
            "repository": "ulfbou/collab",
            "requested": True,
            "available": True,
            "queryStatus": {
                "repository": "ok",
                "openIssues": "ok",
                "openPullRequests": "ok",
                "recentlyMergedPullRequests": "ok",
                "labels": "ok",
                "milestones": "ok",
                "selectedIssue": "ok",
            },
            "errors": [],
            "data": {
                "repository": {
                    "nameWithOwner": "ulfbou/collab",
                    "defaultBranchRef": {"name": "main"},
                },
                "openIssues": [{"number": 61, "title": "Issue 61"}],
                "openPullRequests": [{"number": 83, "title": "Architecture"}],
                "recentlyMergedPullRequests": [{"number": 83, "title": "Architecture"}],
                "labels": [{"name": "priority:foundation"}],
                "milestones": [{"number": 1, "title": "Collab: boundary-centric collaboration model"}],
            },
            "selectedIssue": {
                "number": 61,
                "title": "architecture: establish Current State Record and semantic identity",
                "state": "OPEN",
            },
        },
        "selectedFiles": [
            {
                "path": "README.md",
                "size": 1,
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "status": "included",
                "content": "x",
            }
        ],
        "relationships": {
            "providers": [{"kind": "issue", "id": "61"}],
            "consumers": [{"kind": "pull_request", "id": "83"}],
        },
        "configuration": {
            "includes": ["README.md"],
            "excludes": [".dx"],
            "maxBytes": 262144,
            "recentCommits": 20,
            "github": True,
            "consumerRoot": None,
            "consumerIncludes": [],
            "withFiles": True,
            "selectedIssue": 61,
            "recentClosed": 20,
        },
    }


def capture_state(cwd: Path):
    return {
        "branch": subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip(),
        "status": subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout,
    }


base = base_model()
record_a = module.current_state_record(copy.deepcopy(base), capture_id="capture:one", output_path="out/one.json", rendering={"columns": ["a", "b"], "order": 1})
record_b = module.current_state_record(copy.deepcopy(base), capture_id="capture:two", output_path="out/two.json", rendering={"order": 1, "columns": ["a", "b"]})
assert record_a["captureId"] != record_b["captureId"]
assert record_a["stateIdentity"] == record_b["stateIdentity"]
assert record_a["stateIdentity"].startswith("sha256:v1:")

ordered = copy.deepcopy(base)
ordered["configuration"] = {
    "recentClosed": 20,
    "withFiles": True,
    "selectedIssue": 61,
    "github": True,
    "consumerIncludes": [],
    "consumerRoot": None,
    "maxBytes": 262144,
    "recentCommits": 20,
    "excludes": [".dx"],
    "includes": ["README.md"],
}
ordered["github"]["selectedIssue"] = {
    "state": "OPEN",
    "title": "architecture: establish Current State Record and semantic identity",
    "number": 61,
}
record_ordered = module.current_state_record(copy.deepcopy(ordered), capture_id="capture:three")
assert record_a["stateIdentity"] == record_ordered["stateIdentity"]

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

assert schema["properties"]["schemaVersion"]["const"] == "1.0"
assert schema["properties"]["stateIdentityNormalizationVersion"]["const"] == "1"
assert schema["properties"]["stateIdentity"]["pattern"] == "^sha256:v1:[0-9a-f]{64}$"
assert set(schema["required"]) == {
    "schemaVersion",
    "captureId",
    "stateIdentity",
    "stateIdentityNormalizationVersion",
    "observations",
    "relationships",
    "controllingState",
    "workingState",
    "candidate",
    "classifications",
    "acceptedHistory",
    "verification",
    "completeness",
    "consistency",
    "limitations",
}

compat_from_model = module.repository_state(copy.deepcopy(base))
compat_from_record = module.repository_state(copy.deepcopy(record_a))
assert compat_from_model == compat_from_record

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
    identity_record = module.current_state_record(snapshot, capture_id="capture:sentinel", output_path="output.json", rendering={"z": 1, "a": 2})
    identity_snapshot = copy.deepcopy(identity_record)
    compatibility_record = module.repository_state(identity_record)
    after = capture_state(repo)

    assert snapshot == snapshot_copy
    assert before == after
    assert identity_record == identity_snapshot

print("PASS: current-state identity, projection, schema, and mutation sentinel")
PY
