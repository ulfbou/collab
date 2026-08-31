#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = "1.0"
PROFILE_KINDS = ("session", "context", "delivery", "delta", "pr", "conversation", "selection")
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}\.[0-9]{9}Z-[0-9]+-[0-9a-f]{8}$")
SHA = re.compile(r"^[0-9a-f]{40}$")

PROFILE_FIELDS = {
    "session": {"branch": str},
    "context": {
        "role": str,
        "issue": str,
        "expectedRepo": str,
        "out": str,
        "maxFileBytes": int,
        "recentCommits": int,
        "recentClosed": int,
        "withGitHub": bool,
        "withFiles": bool,
        "allOpenIssueBodies": bool,
        "deliveryBrief": str,
        "consumerRoot": str,
        "includes": list,
        "excludes": list,
        "consumerIncludes": list,
    },
    "delivery": {
        "issue": str,
        "branch": str,
        "title": str,
        "carrier": str,
        "providerSolution": str,
        "consumerRoot": str,
        "consumerSolution": str,
        "toolsDir": str,
        "outputPrefix": str,
        "skipApply": bool,
        "allows": list,
        "focusedTests": list,
        "auditScopes": list,
    },
    "delta": {"outputFile": str},
    "conversation": {"packageType": str, "artifact": str, "evidenceHead": str},
    "selection": {"decision": str, "artifact": str, "evidenceHead": str, "acceptedAt": str},
    "pr": {
        "issue": str,
        "title": str,
        "bodyFile": str,
        "draft": bool,
        "assignees": list,
        "labels": list,
        "reviewers": list,
        "teamReviewers": list,
        "milestone": str,
        "inheritMilestone": bool,
        "prNumber": int,
        "prUrl": str,
        "branch": str,
        "head": str,
        "repository": str,
        "finalReport": str,
        "finalEvidence": str,
        "finalCarrier": str,
    },
}

DEFAULTS = {
    "session": {},
    "context": {
        "role": "",
        "issue": "",
        "expectedRepo": "",
        "out": "",
        "maxFileBytes": 262144,
        "recentCommits": 20,
        "recentClosed": 20,
        "withGitHub": True,
        "withFiles": True,
        "allOpenIssueBodies": False,
        "deliveryBrief": "",
        "consumerRoot": "",
        "includes": [],
        "excludes": [],
        "consumerIncludes": [],
    },
    "delivery": {
        "issue": "",
        "branch": "",
        "title": "",
        "carrier": "",
        "providerSolution": "",
        "consumerRoot": "",
        "consumerSolution": "",
        "toolsDir": "/f/scripts",
        "outputPrefix": "delivery",
        "skipApply": False,
        "allows": [],
        "focusedTests": [],
        "auditScopes": [],
    },
    "delta": {},
    "conversation": {},
    "selection": {},
    "pr": {},
}


class Error(Exception):
    pass


def run(*args: str) -> str:
    process = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise Error(process.stderr.strip() or f"command failed: {' '.join(args)}")
    return process.stdout.strip()


def repo_root() -> Path:
    return Path(run("git", "rev-parse", "--show-toplevel")).resolve()


def origin_repo() -> str:
    url = run("git", "remote", "get-url", "origin")
    if url.endswith(".git"):
        url = url[:-4]
    for prefix in (
        "git@github.com:",
        "https://github.com/",
        "http://github.com/",
        "ssh://git@github.com/",
    ):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    if url.count("/") != 1 or any(ch.isspace() for ch in url):
        raise Error(f"cannot derive GitHub repository from origin: {url}")
    return url


def state_root(root: Path) -> Path:
    return root / ".dx" / "collab"


def profile_path(root: Path, kind: str) -> Path:
    return state_root(root) / "profiles" / f"{kind}.json"


def ensure_kind(kind: str) -> None:
    if kind not in PROFILE_KINDS:
        raise Error(f"unknown profile: {kind}")


def reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise Error(f"refusing unsafe symlink: {path}")


def validate_string_list(value: object, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise Error(f"{field} must be an array of strings")


def validate_values(kind: str, values: object) -> dict:
    if not isinstance(values, dict):
        raise Error("profile values must be an object")
    allowed = PROFILE_FIELDS[kind]
    unknown = set(values) - set(allowed)
    if unknown:
        raise Error(f"unknown {kind} profile fields: {sorted(unknown)}")
    result = dict(DEFAULTS[kind])
    result.update(values)
    for key, value in result.items():
        expected = allowed.get(key)
        if expected is None:
            raise Error(f"unknown {kind} profile field: {key}")
        if expected is list:
            validate_string_list(value, f"{kind}.{key}")
            if kind == "context" and key in {"includes", "excludes", "consumerIncludes"}:
                if any(not item for item in value):
                    raise Error(f"context.{key} must not contain empty paths")
        elif expected is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise Error(f"{kind}.{key} must be an integer")
        elif not isinstance(value, expected):
            raise Error(f"{kind}.{key} must be {expected.__name__}")
    return result


def validate_document(document: object, kind: str, repository: str) -> dict:
    if not isinstance(document, dict):
        raise Error("profile document must be an object")
    expected = {"schemaVersion", "profile", "repository", "values"}
    if set(document) != expected:
        raise Error(f"profile fields differ; expected {sorted(expected)}")
    if document["schemaVersion"] != SCHEMA_VERSION:
        raise Error("unsupported profile schema version")
    if document["profile"] != kind:
        raise Error("profile kind mismatch")
    if document["repository"] != repository:
        raise Error("profile belongs to another repository")
    return validate_values(kind, document["values"])


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    reject_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def assert_private_mode(path: Path) -> None:
    if os.name == "nt" or sys.platform.startswith(("msys", "cygwin")):
        return
    if path.stat().st_mode & 0o077:
        raise Error(f"profile permissions are too broad: {path}")


def load_profile(root: Path, kind: str, repository: str) -> dict:
    path = profile_path(root, kind)
    reject_symlink(path)
    if not path.exists():
        return dict(DEFAULTS[kind])
    if not path.is_file():
        raise Error(f"profile is not a regular file: {path}")
    assert_private_mode(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Error(f"invalid profile {path}: {exc}") from exc
    return validate_document(document, kind, repository)


def save_profile(root: Path, kind: str, repository: str, values: object) -> None:
    checked = validate_values(kind, values)
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "profile": kind,
        "repository": repository,
        "values": checked,
    }
    payload = (json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    atomic_write(profile_path(root, kind), payload)


def clear_profile(root: Path, kind: str | None) -> None:
    kinds = PROFILE_KINDS if kind is None else (kind,)
    for item in kinds:
        ensure_kind(item)
        path = profile_path(root, item)
        reject_symlink(path)
        if path.exists():
            if not path.is_file():
                raise Error(f"profile is not a regular file: {path}")
            path.unlink()


def new_run_id() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S") + f".{now.microsecond:06d}000Z"
    return f"{stamp}-{os.getpid()}-{secrets.token_hex(4)}"


def file_record(path: Path, display_path: str) -> dict:
    reject_symlink(path)
    if not path.is_file():
        raise Error(f"artifact is missing or unsafe: {display_path}")
    data = path.read_bytes()
    return {
        "path": display_path,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def record_run(root: Path, repository: str, args: argparse.Namespace) -> None:
    if not RUN_ID.fullmatch(args.run_id):
        raise Error("invalid run ID")
    if args.status not in ("success", "failure"):
        raise Error("status must be success or failure")
    if args.started < 0:
        raise Error("started must be non-negative")
    if not SHA.fullmatch(args.start_head):
        raise Error("start HEAD must be a 40-character lowercase SHA")

    run_dir = state_root(root) / "runs" / args.run_id
    reject_symlink(run_dir)
    if run_dir.exists():
        raise Error(f"run already exists: {args.run_id}")
    run_dir.mkdir(parents=True, exist_ok=False)

    try:
        artifacts = []
        for item in args.artifact:
            candidate = Path(item)
            absolute = candidate if candidate.is_absolute() else root / candidate
            display = str(candidate).replace("\\", "/")
            artifacts.append(file_record(absolute, display))

        final_head = run("git", "rev-parse", "HEAD")
        if not SHA.fullmatch(final_head):
            raise Error("final HEAD is invalid")
        finished = time.time_ns()
        elapsed_ms = max(0, (finished - args.started) // 1_000_000)
        branch = run("git", "branch", "--show-current")
        document = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": args.run_id,
            "tool": args.tool,
            "toolVersion": args.tool_version,
            "status": args.status,
            "exitStatus": args.exit_status,
            "repository": repository,
            "branch": branch,
            "startHead": args.start_head,
            "finalHead": final_head,
            "startedNanoseconds": args.started,
            "finishedNanoseconds": finished,
            "elapsedMilliseconds": elapsed_ms,
            "failurePhase": args.failure_phase or None,
            "artifacts": artifacts,
        }
        payload = (json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        atomic_write(run_dir / "run.json", payload)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
    except Exception:
        try:
            if run_dir.exists() and not any(run_dir.iterdir()):
                run_dir.rmdir()
        finally:
            raise


def parse_json_argument(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Error(f"invalid JSON: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    load = subparsers.add_parser("load")
    load.add_argument("profile", choices=PROFILE_KINDS)

    save = subparsers.add_parser("save")
    save.add_argument("profile", choices=PROFILE_KINDS)
    save.add_argument("--json", required=True)

    clear = subparsers.add_parser("clear")
    clear.add_argument("profile", choices=PROFILE_KINDS, nargs="?")

    subparsers.add_parser("run-id")

    record = subparsers.add_parser("record")
    record.add_argument("--run-id", required=True)
    record.add_argument("--tool", required=True)
    record.add_argument("--tool-version", default="1.0.0")
    record.add_argument("--status", required=True)
    record.add_argument("--exit-status", required=True, type=int)
    record.add_argument("--started", required=True, type=int)
    record.add_argument("--start-head", required=True)
    record.add_argument("--failure-phase", default="")
    record.add_argument("--artifact", action="append", default=[])
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "run-id":
            print(new_run_id())
            return 0

        root = repo_root()
        repository = origin_repo()
        if args.command == "load":
            print(json.dumps(load_profile(root, args.profile, repository), ensure_ascii=False, sort_keys=True))
        elif args.command == "save":
            save_profile(root, args.profile, repository, parse_json_argument(args.json))
        elif args.command == "clear":
            clear_profile(root, args.profile)
        elif args.command == "record":
            record_run(root, repository, args)
        return 0
    except Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())