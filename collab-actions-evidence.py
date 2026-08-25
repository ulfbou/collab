#!/usr/bin/env python3
"""GitHub Actions Evidence Collector.

Collects completed GitHub Actions failures, transforms them into structured
decision-support records, groups them using exact, approximate, and systemic
similarity, and emits bounded evidence for lessons-learned assessment.

Requires Python 3.11+ and an authenticated GitHub CLI (`gh auth status`).
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

PROGRAM_VERSION = "1.0.0"
OUTPUT_SCHEMA_VERSION = "1.0"
DIAGNOSTIC_SCHEMA_VERSION = "1.0"
SIMILARITY_MODEL_VERSION = "1.0"
KNOWLEDGE_CANDIDATE_POLICY_VERSION = "1.0"

FAILURE_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "action_required"}
CATEGORIES = {
    "USAGE", "ENVIRONMENT", "REPOSITORY", "GIT", "GITHUB", "PROFILE",
    "DX", "CONTRACT", "SCOPE", "VERIFICATION", "ARTIFACT", "WORKFLOW",
    "USER_DECISION",
}
RECOVERY_OUTCOMES = {
    "REPAIR_AND_CONTINUE",
    "REPAIR_AND_STOP_FOR_REVIEW",
    "EMIT_DX_CORRECTION",
    "EMIT_DX_FIRST_DIAGNOSTIC",
    "STOP_FOR_AUTHORITY_DECISION",
}
RESPONSIBILITY_LAYERS = {
    "REPOSITORY", "WORKFLOW", "DX", "TEST", "PROFILE", "GITHUB",
    "ENVIRONMENT", "CONTRACT", "SCOPE", "UNKNOWN",
}

ANSI_RE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
TOKEN_RE = re.compile(r"[a-z0-9_.:/+<>-]+")

# Order matters. More specific signatures precede generic ones.
DIAGNOSTIC_RULES: tuple[dict[str, Any], ...] = (
    {
        "code": "DX_VALIDATION_FAILURE", "category": "DX", "layer": "DX",
        "patterns": (r"\bdx\b.*(?:invalid|error|failed|carrier|payload|encoding|indent)", r"%%(?:dx|file|endblock)"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "SCOPE_CHANGED_PATH", "category": "SCOPE", "layer": "SCOPE",
        "patterns": (r"out of scope", r"outside (?:the )?(?:declared|allowed) scope", r"changed path.*outside"),
        "recovery": "STOP_FOR_AUTHORITY_DECISION", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "CONTRACT_VALIDATION_FAILURE", "category": "CONTRACT", "layer": "CONTRACT",
        "patterns": (r"schema.*(?:invalid|validation|failed)", r"contract.*(?:invalid|failed)", r"required.*(?:missing|absent)"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "TEST_ASSERTION_FAILURE", "category": "VERIFICATION", "layer": "TEST",
        "patterns": (r"assert(?:ion)?(?:error| failed| failure)", r"expected:.+actual:", r"\btests? failed\b", r"\bfail(?:ed|ure):?\s"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "COMPILATION_FAILURE", "category": "VERIFICATION", "layer": "REPOSITORY",
        "patterns": (r"compilation failed", r"build failed", r"\berror [a-z]{1,4}\d{3,5}\b", r"syntaxerror"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "DEPENDENCY_RESOLUTION_FAILURE", "category": "ENVIRONMENT", "layer": "ENVIRONMENT",
        "patterns": (r"could not resolve", r"dependency.*(?:not found|failed)", r"npm err", r"nu\d{4}", r"no matching distribution", r"package.*not found"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "PERMISSION_OR_AUTHENTICATION_FAILURE", "category": "GITHUB", "layer": "GITHUB",
        "patterns": (r"permission denied", r"unauthorized", r"forbidden", r"bad credentials", r"resource not accessible"),
        "recovery": "STOP_FOR_AUTHORITY_DECISION", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "RATE_LIMIT_OR_TRANSIENT_API_FAILURE", "category": "GITHUB", "layer": "GITHUB",
        "patterns": (r"rate limit", r"secondary rate", r"http (?:429|502|503|504)", r"service unavailable"),
        "recovery": "REPAIR_AND_CONTINUE", "repairSafety": "RETRY",
        "mechanicallyRepairable": True,
    },
    {
        "code": "NETWORK_TRANSIENT_FAILURE", "category": "ENVIRONMENT", "layer": "ENVIRONMENT",
        "patterns": (r"connection reset", r"temporary failure", r"name resolution", r"network is unreachable", r"tls handshake timeout"),
        "recovery": "REPAIR_AND_CONTINUE", "repairSafety": "RETRY",
        "mechanicallyRepairable": True,
    },
    {
        "code": "TIMEOUT_FAILURE", "category": "ENVIRONMENT", "layer": "ENVIRONMENT",
        "patterns": (r"timed? out", r"timeout", r"deadline exceeded"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "RUNNER_INFRASTRUCTURE_FAILURE", "category": "ENVIRONMENT", "layer": "ENVIRONMENT",
        "patterns": (r"runner.*(?:lost|offline|unavailable)", r"hosted runner", r"the runner has received a shutdown signal", r"no space left on device"),
        "recovery": "REPAIR_AND_CONTINUE", "repairSafety": "RETRY",
        "mechanicallyRepairable": True,
    },
    {
        "code": "WORKFLOW_CONFIGURATION_FAILURE", "category": "WORKFLOW", "layer": "WORKFLOW",
        "patterns": (r"workflow.*(?:invalid|syntax|configuration)", r"startup failure", r"unrecognized named-value", r"unexpected value"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
    {
        "code": "PROCESS_EXIT_FAILURE", "category": "VERIFICATION", "layer": "UNKNOWN",
        "patterns": (r"process completed with exit code", r"exited with (?:code|status)", r"command failed"),
        "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
        "mechanicallyRepairable": False,
    },
)

ERROR_LINE_RE = re.compile(
    r"(?i)(?:error|failed|failure|fatal|exception|traceback|assert|panic|"
    r"segmentation fault|npm err|exit(?:ed)? (?:with )?(?:code|status)|"
    r"not found|permission denied|timed? out|unauthorized|forbidden|"
    r"##\[error\]|warning:.*(?:retry|failure))"
)


class AppError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class RunObservation:
    repository: str
    run_id: int
    attempt: int
    run_number: int
    workflow_id: int | None
    workflow: str
    workflow_path: str
    branch: str
    event: str
    commit: str
    title: str
    actor: str
    created_at: str
    updated_at: str
    conclusion: str
    url: str


@dataclasses.dataclass(frozen=True)
class FailureObservation:
    repository: str
    run_id: int
    attempt: int
    run_number: int
    workflow: str
    workflow_path: str
    branch: str
    event: str
    commit: str
    title: str
    actor: str
    created_at: str
    conclusion: str
    url: str
    job_id: int | None
    job: str
    matrix: str
    runner_name: str
    runner_group: str
    step_number: int | None
    step: str
    evidence: str
    evidence_sha256: str
    evidence_retrieval_status: str
    exact_fingerprint: str


@dataclasses.dataclass(frozen=True)
class Diagnostic:
    schemaVersion: str
    code: str
    category: str
    severity: str
    phase: str
    mechanicallyRepairable: bool
    repairSafety: str
    message: str
    evidence: dict[str, Any]
    action: dict[str, Any]
    mutationsPerformed: list[str]
    artifacts: list[str]


@dataclasses.dataclass
class ApproximateFamily:
    family_id: str
    representative: FailureObservation
    occurrences: list[FailureObservation]
    cohesion: float


@dataclasses.dataclass
class SystemicFamily:
    systemic_id: str
    key: str
    member_family_ids: list[str]
    occurrence_count: int
    repositories: list[str]
    workflows: list[str]
    diagnostic_codes: list[str]


def execute(argv: Sequence[str], *, cwd: Path | None = None, text: bool = True,
            check: bool = True) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(list(argv), cwd=cwd, text=text, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise AppError(f"required command not found: {argv[0]}") from exc
    if check and cp.returncode:
        error = cp.stderr.strip() if text else cp.stderr.decode("utf-8", "replace").strip()
        raise AppError(f"command failed ({cp.returncode}): {' '.join(argv)}\n{error}")
    return cp


def gh_json(args: Sequence[str], *, cwd: Path | None = None) -> Any:
    cp = execute(["gh", *args], cwd=cwd)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise AppError(f"gh returned invalid JSON: gh {' '.join(args)}") from exc


def canonical_repo(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\.git$", "", value)
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        raise AppError(f"invalid repository {value!r}; expected OWNER/REPO")
    return value


def git_root(start: Path) -> Path:
    cp = execute(["git", "rev-parse", "--show-toplevel"], cwd=start, check=False)
    if cp.returncode:
        raise AppError("not inside a Git repository; specify --repo OWNER/REPO")
    return Path(cp.stdout.strip()).resolve()


def repo_from_root(root: Path) -> str:
    cp = execute(["git", "remote", "get-url", "origin"], cwd=root, check=False)
    if cp.returncode or not cp.stdout.strip():
        raise AppError(f"cannot derive repository from origin in {root}")
    return canonical_repo(cp.stdout)


def initialized_submodules(root: Path) -> list[Path]:
    cp = execute(["git", "submodule", "foreach", "--quiet",
                  "printf '%s\\n' \"$toplevel/$sm_path\""], cwd=root, check=False)
    if cp.returncode:
        return []
    return [Path(line).resolve() for line in cp.stdout.splitlines() if line.strip()]


def resolve_repositories(explicit: list[str], include_submodules: bool) -> list[str]:
    if explicit:
        return list(dict.fromkeys(canonical_repo(item) for item in explicit))
    root = git_root(Path.cwd())
    repositories = [repo_from_root(root)]
    if include_submodules:
        for submodule in initialized_submodules(root):
            try:
                repositories.append(repo_from_root(submodule))
            except AppError as exc:
                print(f"warning: {exc}", file=sys.stderr)
    return list(dict.fromkeys(repositories))


def parse_timestamp(raw: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def api_pages(endpoint: str, *, fields: list[str], page_key: str,
              max_pages: int = 100) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        args = ["api", "--method", "GET", "-H", "X-GitHub-Api-Version: 2022-11-28",
                endpoint, "-f", "per_page=100", "-f", f"page={page}"]
        for field in fields:
            args.extend(["-f", field])
        data = gh_json(args)
        items = data.get(page_key, []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise AppError(f"unexpected API response for {endpoint}")
        result.extend(items)
        if len(items) < 100:
            return result
    raise AppError(f"pagination safety limit reached for {endpoint}")


def list_runs(repo: str, since: dt.datetime, until: dt.datetime,
              conclusions: set[str]) -> list[RunObservation]:
    created = f"created={iso_utc(since)}..{iso_utc(until)}"
    raw = api_pages(f"repos/{repo}/actions/runs",
                    fields=["status=completed", created], page_key="workflow_runs")
    result = []
    for item in raw:
        conclusion = item.get("conclusion") or ""
        created_at = item.get("created_at") or ""
        if conclusion not in conclusions or not created_at:
            continue
        stamp = parse_timestamp(created_at)
        if not since <= stamp <= until:
            continue
        result.append(RunObservation(
            repository=repo,
            run_id=int(item["id"]),
            attempt=int(item.get("run_attempt") or 1),
            run_number=int(item.get("run_number") or 0),
            workflow_id=item.get("workflow_id"),
            workflow=item.get("name") or "(unknown workflow)",
            workflow_path=item.get("path") or "",
            branch=item.get("head_branch") or "(unknown branch)",
            event=item.get("event") or "",
            commit=item.get("head_sha") or "",
            title=item.get("display_title") or "",
            actor=(item.get("actor") or {}).get("login") or "",
            created_at=created_at,
            updated_at=item.get("updated_at") or "",
            conclusion=conclusion,
            url=item.get("html_url") or "",
        ))
    return sorted(result, key=lambda item: (item.created_at, item.repository, item.run_id), reverse=True)


def list_jobs(run: RunObservation) -> list[dict[str, Any]]:
    return api_pages(
        f"repos/{run.repository}/actions/runs/{run.run_id}/attempts/{run.attempt}/jobs",
        fields=[], page_key="jobs",
    )


def download_job_log(repo: str, job_id: int, retries: int) -> tuple[bytes, str]:
    endpoint = f"repos/{repo}/actions/jobs/{job_id}/logs"
    status = "unavailable"
    for attempt in range(retries + 1):
        cp = execute(["gh", "api", "-H", "X-GitHub-Api-Version: 2022-11-28", endpoint],
                     text=False, check=False)
        if cp.returncode == 0:
            return cp.stdout, "ok"
        status = cp.stderr.decode("utf-8", "replace").strip() or f"exit-{cp.returncode}"
        if attempt < retries:
            time.sleep(2 ** attempt)
    return b"", status


def decode_log(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                raw = b"\n".join(archive.read(name) for name in sorted(archive.namelist())
                                   if not name.endswith("/"))
        except zipfile.BadZipFile:
            pass
    return ANSI_RE.sub(b"", raw).decode("utf-8", "replace")


def normalize_line(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"^\d{4}-\d\d-\d\d[t ]\d\d:\d\d:\d\d(?:\.\d+)?z?\s*", "", text)
    text = re.sub(r"\b[0-9a-f]{7,64}\b", "<sha>", text)
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", "<uuid>", text)
    text = re.sub(r"(?:[a-z]:)?/(?:home/runner/work|__w|runner/_work)/\S+", "<workspace>", text)
    text = re.sub(r"[a-z]:\\(?:[^\s:\"']+\\)+[^\s:\"']+", "<path>", text)
    text = re.sub(r"\b\d{4}-\d\d-\d\d[t ]\d\d:\d\d:\d\d(?:\.\d+)?(?:z|[+-]\d\d:\d\d)?\b", "<timestamp>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds?|minutes?|mins?|hours?|hrs?)\b", "<duration>", text)
    text = re.sub(r"\b(?:run|job|request|trace|correlation)[-_ ]?id[:= ]+\d+\b", "<id>", text)
    text = re.sub(r"\b\d{5,}\b", "<number>", text)
    text = re.sub(r"\s+", " ", text)
    return text


def evidence_from_log(log: str, *, max_lines: int, max_chars: int) -> str:
    interesting: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    for raw in log.splitlines():
        line = normalize_line(raw)
        if not line or line in seen:
            continue
        fallback.append(line)
        if ERROR_LINE_RE.search(line):
            seen.add(line)
            interesting.append(line)
    selected = interesting[-max_lines:] if interesting else fallback[-max_lines:]
    return "\n".join(selected)[-max_chars:]


def matrix_suffix(job: str) -> str:
    match = re.search(r"\(([^()]*)\)\s*$|\[([^\[\]]*)\]\s*$", job)
    return next((part for part in match.groups() if part is not None), "") if match else ""


def normalized_identity(*values: str) -> str:
    return "\x1f".join(normalize_line(value) for value in values)


def exact_fingerprint(workflow: str, job: str, step: str, evidence: str) -> str:
    return hashlib.sha256(normalized_identity(workflow, job, step, evidence).encode()).hexdigest()[:20]


def extract_run_failures(run: RunObservation, *, max_lines: int, max_chars: int,
                         retries: int, include_cancelled_jobs: bool) -> list[FailureObservation]:
    jobs = list_jobs(run)
    result: list[FailureObservation] = []
    accepted = set(FAILURE_CONCLUSIONS)
    if include_cancelled_jobs:
        accepted.add("cancelled")
    for job in jobs:
        if (job.get("conclusion") or "") not in accepted:
            continue
        job_id = int(job["id"])
        raw, retrieval = download_job_log(run.repository, job_id, retries)
        evidence = evidence_from_log(decode_log(raw), max_lines=max_lines, max_chars=max_chars)
        failed_steps = [step for step in job.get("steps", []) if step.get("conclusion") in accepted]
        if not failed_steps:
            failed_steps = [{"name": "(job-level failure)", "number": None}]
        job_name = job.get("name") or "(unknown job)"
        for step in failed_steps:
            step_name = step.get("name") or "(unknown step)"
            result.append(FailureObservation(
                repository=run.repository, run_id=run.run_id, attempt=run.attempt,
                run_number=run.run_number, workflow=run.workflow,
                workflow_path=run.workflow_path, branch=run.branch, event=run.event,
                commit=run.commit, title=run.title, actor=run.actor,
                created_at=run.created_at, conclusion=run.conclusion, url=run.url,
                job_id=job_id, job=job_name, matrix=matrix_suffix(job_name),
                runner_name=job.get("runner_name") or "",
                runner_group=job.get("runner_group_name") or "",
                step_number=step.get("number"), step=step_name, evidence=evidence,
                evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
                evidence_retrieval_status=retrieval,
                exact_fingerprint=exact_fingerprint(run.workflow, job_name, step_name, evidence),
            ))
    if not result:
        evidence = f"workflow concluded with {run.conclusion}; no failed job was reported"
        result.append(FailureObservation(
            repository=run.repository, run_id=run.run_id, attempt=run.attempt,
            run_number=run.run_number, workflow=run.workflow,
            workflow_path=run.workflow_path, branch=run.branch, event=run.event,
            commit=run.commit, title=run.title, actor=run.actor,
            created_at=run.created_at, conclusion=run.conclusion, url=run.url,
            job_id=None, job="(workflow-level failure)", matrix="", runner_name="",
            runner_group="", step_number=None, step="(no failed job reported)",
            evidence=evidence, evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
            evidence_retrieval_status="no-failed-job",
            exact_fingerprint=exact_fingerprint(run.workflow, "workflow-level", run.conclusion, evidence),
        ))
    return result


def classify_diagnostic(failure: FailureObservation) -> Diagnostic:
    searchable = normalize_line("\n".join((failure.workflow, failure.job, failure.step, failure.evidence)))
    selected: dict[str, Any] | None = None
    for rule in DIAGNOSTIC_RULES:
        if any(re.search(pattern, searchable, re.IGNORECASE | re.DOTALL) for pattern in rule["patterns"]):
            selected = rule
            break
    if selected is None:
        selected = {
            "code": "UNCLASSIFIED_ACTION_FAILURE", "category": "WORKFLOW", "layer": "UNKNOWN",
            "recovery": "EMIT_DX_FIRST_DIAGNOSTIC", "repairSafety": "AUTHORITY_STOP",
            "mechanicallyRepairable": False,
        }
    action_kind = selected["recovery"]
    command = f"gh run view {failure.run_id} --repo {failure.repository} --attempt {failure.attempt} --log-failed"
    message = f"{failure.workflow} / {failure.job} / {failure.step} failed with {failure.conclusion}."
    return Diagnostic(
        schemaVersion=DIAGNOSTIC_SCHEMA_VERSION,
        code=selected["code"], category=selected["category"], severity="error",
        phase="github-actions-analysis",
        mechanicallyRepairable=bool(selected["mechanicallyRepairable"]),
        repairSafety=selected["repairSafety"], message=message,
        evidence={
            "repository": failure.repository, "runId": failure.run_id,
            "attempt": failure.attempt, "jobId": failure.job_id,
            "workflow": failure.workflow, "job": failure.job, "step": failure.step,
            "evidenceSha256": failure.evidence_sha256,
            "retrievalStatus": failure.evidence_retrieval_status,
        },
        action={"kind": action_kind, "command": command},
        mutationsPerformed=[], artifacts=[],
    )


def responsibility_layer(diagnostic: Diagnostic) -> str:
    for rule in DIAGNOSTIC_RULES:
        if rule["code"] == diagnostic.code:
            return rule["layer"]
    return "UNKNOWN"


def token_set(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(normalize_line(value)) if len(token) > 1}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right) if left or right else 0.0


def name_similarity(left: str, right: str) -> float:
    return jaccard(token_set(left), token_set(right))


def similarity(left: FailureObservation, right: FailureObservation,
               cross_repository: bool) -> float:
    repository = 1.0 if left.repository == right.repository else 0.0
    workflow = max(
        1.0 if left.workflow_path and left.workflow_path == right.workflow_path else 0.0,
        name_similarity(left.workflow, right.workflow),
    )
    job = name_similarity(left.job, right.job)
    step = name_similarity(left.step, right.step)
    evidence = jaccard(token_set(left.evidence), token_set(right.evidence))
    matrix = 1.0 if left.matrix and left.matrix == right.matrix else 0.0
    if not cross_repository and left.repository != right.repository:
        return 0.0
    if cross_repository:
        return 0.10 * repository + 0.18 * workflow + 0.20 * job + 0.18 * step + 0.31 * evidence + 0.03 * matrix
    return 0.21 * workflow + 0.22 * job + 0.20 * step + 0.34 * evidence + 0.03 * matrix


def cluster_approximate(failures: list[FailureObservation], threshold: float,
                        cross_repository: bool) -> list[ApproximateFamily]:
    exact_groups: dict[str, list[FailureObservation]] = defaultdict(list)
    for failure in failures:
        exact_groups[failure.exact_fingerprint].append(failure)
    leaders = sorted(
        (max(group, key=lambda item: (len(item.evidence), item.created_at))
         for group in exact_groups.values()),
        key=lambda item: (len(item.evidence), item.created_at, item.exact_fingerprint),
        reverse=True,
    )
    families: list[ApproximateFamily] = []
    for leader in leaders:
        group = exact_groups[leader.exact_fingerprint]
        best: ApproximateFamily | None = None
        best_score = -1.0
        for family in families:
            score = similarity(leader, family.representative, cross_repository)
            if score > best_score:
                best, best_score = family, score
        if best is not None and best_score >= threshold:
            best.occurrences.extend(group)
        else:
            families.append(ApproximateFamily("", leader, list(group), 1.0))
    for family in families:
        family.occurrences.sort(key=lambda item: (item.created_at, item.repository, item.run_id), reverse=True)
        scores = [similarity(family.representative, item, cross_repository) for item in family.occurrences]
        family.cohesion = sum(scores) / len(scores)
        payload = "\x1f".join(sorted(item.exact_fingerprint for item in family.occurrences))
        family.family_id = "F-" + hashlib.sha256(payload.encode()).hexdigest()[:12].upper()
    return sorted(families,
                  key=lambda family: (len(family.occurrences), family.occurrences[0].created_at, family.family_id),
                  reverse=True)


def systemic_key(family: ApproximateFamily) -> str:
    diagnostic = classify_diagnostic(family.representative)
    layer = responsibility_layer(diagnostic)
    important = sorted(token_set(family.representative.evidence) - {
        "error", "failed", "failure", "process", "completed", "exit", "code",
        "runner", "github", "actions", "with", "from", "that", "this",
    })[:8]
    return "|".join([layer, diagnostic.code, *important])


def cluster_systemic(families: list[ApproximateFamily]) -> list[SystemicFamily]:
    grouped: dict[str, list[ApproximateFamily]] = defaultdict(list)
    for family in families:
        grouped[systemic_key(family)].append(family)
    result = []
    for key, members in grouped.items():
        occurrences = [item for family in members for item in family.occurrences]
        diagnostics = sorted({classify_diagnostic(family.representative).code for family in members})
        result.append(SystemicFamily(
            systemic_id="S-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper(),
            key=key,
            member_family_ids=sorted(family.family_id for family in members),
            occurrence_count=len(occurrences),
            repositories=sorted({item.repository for item in occurrences}),
            workflows=sorted({item.workflow for item in occurrences}),
            diagnostic_codes=diagnostics,
        ))
    return sorted(result, key=lambda item: (item.occurrence_count, item.systemic_id), reverse=True)


def trend(items: list[FailureObservation], since: dt.datetime, until: dt.datetime) -> str:
    midpoint = since + (until - since) / 2
    old = sum(parse_timestamp(item.created_at) < midpoint for item in items)
    new = len(items) - old
    if old == 0 and new:
        return "NEW"
    ratio = (new + 0.5) / (old + 0.5)
    if ratio >= 1.75:
        return "INCREASING"
    if ratio <= 0.57:
        return "DECREASING"
    return "STEADY"


def rerun_classification(items: list[FailureObservation], all_runs: list[RunObservation]) -> dict[str, Any]:
    by_identity: dict[tuple[str, str, str], list[RunObservation]] = defaultdict(list)
    for run in all_runs:
        by_identity[(run.repository, run.workflow_path or run.workflow, run.commit)].append(run)
    matching = []
    for item in items:
        matching.extend(by_identity.get((item.repository, item.workflow_path or item.workflow, item.commit), []))
    attempts = sorted({(run.repository, run.run_id, run.attempt, run.conclusion) for run in matching})
    failed_attempts = [entry for entry in attempts if entry[3] in FAILURE_CONCLUSIONS]
    successful_attempts = [entry for entry in attempts if entry[3] == "success"]
    if successful_attempts and failed_attempts:
        classification = "PROBABLE_FLAKE"
        confidence = "moderate"
    elif len(failed_attempts) >= 2:
        classification = "PROBABLE_DETERMINISTIC"
        confidence = "moderate"
    else:
        classification = "INSUFFICIENT_RERUN_EVIDENCE"
        confidence = "indeterminate"
    return {
        "classification": classification,
        "confidence": confidence,
        "observedAttempts": [
            {"repository": repo, "runId": run_id, "attempt": attempt, "conclusion": conclusion}
            for repo, run_id, attempt, conclusion in attempts
        ],
    }


def knowledge_candidate(family: ApproximateFamily, diagnostic: Diagnostic,
                        recurring_after_repair: bool = False) -> dict[str, Any]:
    occurrences = family.occurrences
    repositories = {item.repository for item in occurrences}
    exact_fingerprints = {item.exact_fingerprint for item in occurrences}
    triggers: list[str] = []
    weights = 0.0
    if len(occurrences) >= 3:
        triggers.append("REPEATED_FAILURE")
        weights += min(0.35, 0.10 + 0.05 * len(occurrences))
    if len(repositories) >= 2:
        triggers.append("CROSS_REPOSITORY")
        weights += 0.30
    if len(exact_fingerprints) >= 2:
        triggers.append("RECURRING_VARIANTS")
        weights += 0.15
    if recurring_after_repair:
        triggers.append("RECURRED_AFTER_REPAIR")
        weights += 0.35
    if diagnostic.category in {"DX", "CONTRACT", "SCOPE"} and len(occurrences) >= 2:
        triggers.append("REUSABLE_BOUNDARY_LESSON")
        weights += 0.15
    score = min(1.0, weights)
    if score >= 0.70:
        confidence = "high"
    elif score >= 0.40:
        confidence = "moderate"
    elif score > 0:
        confidence = "low"
    else:
        confidence = "indeterminate"
    candidate = bool(triggers and (len(occurrences) >= 3 or len(repositories) >= 2 or recurring_after_repair))
    return {
        "policyVersion": KNOWLEDGE_CANDIDATE_POLICY_VERSION,
        "candidate": candidate,
        "confidence": confidence,
        "confidenceScore": round(score, 3),
        "triggers": triggers,
        "proposedCheckpointOutcome": "ADD_KNOWLEDGE_VERSION" if candidate else "NO_KNOWLEDGE_CHANGE",
        "requiresHumanAcceptance": True,
        "candidateSummary": (
            f"Review {diagnostic.code} as a reusable lesson based on {len(occurrences)} "
            f"occurrence(s) across {len(repositories)} repository/repositories."
            if candidate else "No knowledge-capture threshold was met."
        ),
        "revisitTrigger": "Reassess if the family recurs, crosses repositories, or survives an attempted correction.",
    }


def decision_record(family: ApproximateFamily, all_runs: list[RunObservation],
                    since: dt.datetime, until: dt.datetime) -> dict[str, Any]:
    representative = family.representative
    diagnostic = classify_diagnostic(representative)
    layer = responsibility_layer(diagnostic)
    occurrence_count = len(family.occurrences)
    distinct_runs = len({(item.repository, item.run_id, item.attempt) for item in family.occurrences})
    reruns = rerun_classification(family.occurrences, all_runs)
    recurrence = trend(family.occurrences, since, until)
    if recurrence != "NEW" and occurrence_count >= 3:
        recurrence = "RECURRING_" + recurrence
    candidate = knowledge_candidate(family, diagnostic)
    evidence_statuses = dict(Counter(item.evidence_retrieval_status for item in family.occurrences))
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "familyId": family.family_id,
        "observation": {
            "representative": dataclasses.asdict(representative),
            "occurrenceCount": occurrence_count,
            "distinctRuns": distinct_runs,
            "repositories": dict(Counter(item.repository for item in family.occurrences).most_common()),
            "workflows": dict(Counter(item.workflow for item in family.occurrences).most_common()),
            "branches": dict(Counter(item.branch for item in family.occurrences).most_common()),
            "jobs": dict(Counter(item.job for item in family.occurrences).most_common()),
            "steps": dict(Counter(item.step for item in family.occurrences).most_common()),
            "firstSeen": min(item.created_at for item in family.occurrences),
            "lastSeen": max(item.created_at for item in family.occurrences),
            "evidenceRetrievalStatus": evidence_statuses,
        },
        "diagnostic": dataclasses.asdict(diagnostic),
        "similarity": {
            "modelVersion": SIMILARITY_MODEL_VERSION,
            "exactFingerprints": sorted({item.exact_fingerprint for item in family.occurrences}),
            "approximateFamilyId": family.family_id,
            "cohesion": round(family.cohesion, 3),
        },
        "classification": {
            "responsibilityLayer": layer,
            "recurrence": recurrence,
            "rerunAssessment": reruns,
        },
        "recovery": {
            "outcome": diagnostic.action["kind"],
            "repairSafety": diagnostic.repairSafety,
            "mechanicallyRepairable": diagnostic.mechanicallyRepairable,
            "automaticActionPerformed": False,
            "reasonNotRepaired": (
                "This collector is read-only and cannot prove a complete deterministic correction."
            ),
        },
        "knowledgeCandidate": candidate,
        "nextAction": diagnostic.action,
        "occurrences": [dataclasses.asdict(item) for item in family.occurrences],
    }


def compare_baseline(records: list[dict[str, Any]], baseline_path: Path | None) -> dict[str, Any]:
    current = {record["familyId"] for record in records}
    if baseline_path is None:
        return {"available": False, "newFamilies": sorted(current), "recurringFamilies": [], "resolvedFamilies": []}
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppError(f"cannot read baseline {baseline_path}: {exc}") from exc
    old_records = baseline.get("families", []) if isinstance(baseline, dict) else []
    old = {item.get("familyId") for item in old_records if isinstance(item, dict) and item.get("familyId")}
    return {
        "available": True,
        "baseline": str(baseline_path),
        "newFamilies": sorted(current - old),
        "recurringFamilies": sorted(current & old),
        "resolvedFamilies": sorted(old - current),
    }


def lessons_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for record in records:
        candidate = record["knowledgeCandidate"]
        if not candidate["candidate"]:
            continue
        observation = record["observation"]
        diagnostic = record["diagnostic"]
        candidates.append({
            "schemaVersion": OUTPUT_SCHEMA_VERSION,
            "familyId": record["familyId"],
            "diagnosticCode": diagnostic["code"],
            "category": diagnostic["category"],
            "responsibilityLayer": record["classification"]["responsibilityLayer"],
            "evidence": {
                "occurrences": observation["occurrenceCount"],
                "distinctRuns": observation["distinctRuns"],
                "repositories": list(observation["repositories"]),
                "firstSeen": observation["firstSeen"],
                "lastSeen": observation["lastSeen"],
                "familyCohesion": record["similarity"]["cohesion"],
            },
            "lessonCandidate": candidate["candidateSummary"],
            "confidence": candidate["confidence"],
            "confidenceScore": candidate["confidenceScore"],
            "triggers": candidate["triggers"],
            "recommendedKnowledgeCheckpoint": candidate["proposedCheckpointOutcome"],
            "requiresHumanAcceptance": True,
            "nextAction": record["nextAction"],
        })
    return sorted(candidates, key=lambda item: (item["confidenceScore"], item["evidence"]["occurrences"]), reverse=True)


def safe_dx_path(raw: str) -> str:
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise AppError(f"unsafe DX path: {raw}")
    return path.as_posix()


def dx_quote_payload_line(line: str) -> str:
    return ("        " if line.startswith("%%") else "    ") + line


def make_readonly_dx(files: dict[str, bytes]) -> bytes:
    output = ["%%DX v1.3.1\n"]
    for name in sorted(files):
        name = safe_dx_path(name)
        data = files[name]
        if data.startswith(b"\xef\xbb\xbf") or b"\x00" in data:
            raise AppError(f"readonly evidence must be UTF-8 text without BOM: {name}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError(f"readonly evidence is not UTF-8: {name}") from exc
        text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        output.append(f'%%FILE path="{name}" readonly="true"\n')
        if text:
            output.extend(dx_quote_payload_line(line) + "\n" for line in text.split("\n"))
        output.append("%%ENDBLOCK\n")
    output.append("%%END\n")
    encoded = "".join(output).encode("utf-8")
    validate_generated_dx(encoded, files)
    return encoded


def validate_generated_dx(carrier: bytes, expected: dict[str, bytes]) -> None:
    text = carrier.decode("utf-8")
    if "\r" in text or not text.startswith("%%DX v1.3.1\n") or not text.endswith("%%END\n"):
        raise AppError("generated DX carrier failed canonical framing validation")
    lines = text.splitlines()
    found: dict[str, bytes] = {}
    attrs_re = re.compile(r'(\w+)="([^"]*)"')
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("%%FILE"):
            attrs = dict(attrs_re.findall(line))
            name = attrs.get("path")
            if not name or attrs.get("readonly") != "true" or name in found:
                raise AppError("generated DX carrier has invalid FILE attributes")
            index += 1
            body = []
            while index < len(lines) and lines[index] != "%%ENDBLOCK":
                payload = lines[index]
                if not payload.startswith("    "):
                    raise AppError("generated DX carrier has unindented payload")
                payload = payload[4:]
                if payload.startswith("    %%"):
                    payload = payload[4:]
                body.append(payload)
                index += 1
            if index >= len(lines):
                raise AppError("generated DX carrier has unterminated FILE block")
            found[name] = (("\n".join(body) + "\n") if body else "").encode()
        index += 1
    normalized_expected = {
        name: (data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + ("\n" if data else "")).encode()
        for name, data in expected.items()
    }
    if found != normalized_expected:
        raise AppError("generated DX carrier failed decoded-byte comparison")


def atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise AppError(f"refusing to replace symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise AppError(f"refusing unsafe output parent: {path.parent}")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def compact(value: str, limit: int = 360) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    baseline = report["baselineComparison"]
    lines = [
        "# GitHub Actions Evidence Collector", "",
        f"Generated: `{report['generatedAt']}`", "",
        f"Window: `{report['window']['since']}` through `{report['window']['until']}`", "",
        f"Repositories: {', '.join(f'`{repo}`' for repo in report['repositories'])}", "",
        "## Executive summary", "",
        f"- Failed runs observed: **{summary['failedRuns']}**",
        f"- Failure occurrences: **{summary['failureOccurrences']}**",
        f"- Exact fingerprints: **{summary['exactFingerprints']}**",
        f"- Approximate families: **{summary['approximateFamilies']}**",
        f"- Systemic families: **{summary['systemicFamilies']}**",
        f"- Knowledge candidates: **{summary['knowledgeCandidates']}**",
        f"- Degraded evidence occurrences: **{summary['degradedEvidenceOccurrences']}**",
        "",
        "## Baseline comparison", "",
        f"- Baseline available: **{'yes' if baseline['available'] else 'no'}**",
        f"- New families: **{len(baseline['newFamilies'])}**",
        f"- Recurring families: **{len(baseline['recurringFamilies'])}**",
        f"- Resolved families: **{len(baseline['resolvedFamilies'])}**",
        "",
    ]
    if not report["families"]:
        return "\n".join(lines + ["No matching failures were found.", ""])
    lines.extend(["## Decision-support records", ""])
    for number, record in enumerate(report["families"], 1):
        observation = record["observation"]
        diagnostic = record["diagnostic"]
        classification = record["classification"]
        recovery = record["recovery"]
        candidate = record["knowledgeCandidate"]
        signature = compact(observation["representative"]["evidence"]) or "(no diagnostic evidence recovered)"
        lines.extend([
            f"### {number}. {record['familyId']}: {diagnostic['code']}", "",
            f"**{diagnostic['message']}**", "",
            f"- Category: `{diagnostic['category']}`",
            f"- Responsibility layer: `{classification['responsibilityLayer']}`",
            f"- Recovery outcome: `{recovery['outcome']}`",
            f"- Repair safety: `{recovery['repairSafety']}`",
            f"- Recurrence: `{classification['recurrence']}`",
            f"- Rerun assessment: `{classification['rerunAssessment']['classification']}`",
            f"- Occurrences: **{observation['occurrenceCount']}** across **{observation['distinctRuns']}** run(s)",
            f"- Cohesion: **{record['similarity']['cohesion']:.3f}**",
            f"- Repositories: {', '.join(f'{key} ({value})' for key, value in observation['repositories'].items())}",
            f"- First seen: `{observation['firstSeen']}`",
            f"- Last seen: `{observation['lastSeen']}`",
            f"- Signature: `{signature}`",
            f"- Knowledge candidate: **{'yes' if candidate['candidate'] else 'no'}**, confidence `{candidate['confidence']}`",
            f"- Next command: `{record['nextAction']['command']}`", "",
        ])
    lines.extend(["## Candidate lessons learned", ""])
    if not report["lessonsCandidates"]:
        lines.extend(["No family met the configured knowledge-capture thresholds.", ""])
    else:
        for lesson in report["lessonsCandidates"]:
            lines.extend([
                f"### {lesson['familyId']}: {lesson['diagnosticCode']}", "",
                lesson["lessonCandidate"], "",
                f"- Confidence: `{lesson['confidence']}` ({lesson['confidenceScore']:.3f})",
                f"- Triggers: {', '.join(f'`{trigger}`' for trigger in lesson['triggers'])}",
                f"- Proposed checkpoint: `{lesson['recommendedKnowledgeCheckpoint']}`",
                "- Human acceptance required: `true`", "",
            ])
    lines.extend(["## Systemic families", ""])
    for item in report["systemicFamilies"]:
        lines.extend([
            f"### {item['systemic_id']}", "",
            f"- Occurrences: **{item['occurrence_count']}**",
            f"- Member families: {', '.join(f'`{value}`' for value in item['member_family_ids'])}",
            f"- Repositories: {', '.join(f'`{value}`' for value in item['repositories'])}",
            f"- Workflows: {', '.join(f'`{value}`' for value in item['workflows'])}",
            f"- Diagnostic codes: {', '.join(f'`{value}`' for value in item['diagnostic_codes'])}", "",
        ])
    lines.extend([
        "## Interpretation boundaries", "",
        "- Similarity and temporal correlation are advisory evidence, not proof of causation.",
        "- The collector performs no repository, workflow, issue, pull request, priority, or knowledge mutation.",
        "- Knowledge candidates require explicit human acceptance through the knowledge checkpoint.",
        "- Degraded evidence remains visible rather than being silently discarded.", "",
    ])
    return "\n".join(lines)


def diagnostic_vocabulary() -> dict[str, Any]:
    codes = []
    for rule in DIAGNOSTIC_RULES:
        codes.append({
            "code": rule["code"], "category": rule["category"],
            "responsibilityLayer": rule["layer"], "repairSafety": rule["repairSafety"],
            "recoveryOutcome": rule["recovery"],
            "mechanicallyRepairable": rule["mechanicallyRepairable"],
        })
    codes.append({
        "code": "UNCLASSIFIED_ACTION_FAILURE", "category": "WORKFLOW",
        "responsibilityLayer": "UNKNOWN", "repairSafety": "AUTHORITY_STOP",
        "recoveryOutcome": "EMIT_DX_FIRST_DIAGNOSTIC", "mechanicallyRepairable": False,
    })
    return {
        "schemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
        "vocabularyVersion": "1.0.0",
        "categories": sorted(CATEGORIES),
        "recoveryOutcomes": sorted(RECOVERY_OUTCOMES),
        "responsibilityLayers": sorted(RESPONSIBILITY_LAYERS),
        "codes": codes,
        "compatibilityPolicy": {
            "stableContract": "code",
            "proseMayEvolve": True,
            "unknownCodesMustBePreserved": True,
        },
    }


def build_report(repositories: list[str], since: dt.datetime, until: dt.datetime,
                 runs: list[RunObservation], failures: list[FailureObservation],
                 families: list[ApproximateFamily], systemic: list[SystemicFamily],
                 baseline: Path | None, configuration: dict[str, Any]) -> dict[str, Any]:
    records = [decision_record(family, runs, since, until) for family in families]
    lessons = lessons_candidates(records)
    comparison = compare_baseline(records, baseline)
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "collectorVersion": PROGRAM_VERSION,
        "generatedAt": iso_utc(dt.datetime.now(dt.timezone.utc)),
        "window": {"since": iso_utc(since), "until": iso_utc(until)},
        "repositories": repositories,
        "configuration": configuration,
        "summary": {
            "failedRuns": len(runs),
            "failureOccurrences": len(failures),
            "exactFingerprints": len({item.exact_fingerprint for item in failures}),
            "approximateFamilies": len(families),
            "systemicFamilies": len(systemic),
            "knowledgeCandidates": len(lessons),
            "degradedEvidenceOccurrences": sum(item.evidence_retrieval_status != "ok" for item in failures),
        },
        "baselineComparison": comparison,
        "families": records,
        "systemicFamilies": [dataclasses.asdict(item) for item in systemic],
        "lessonsCandidates": lessons,
        "diagnosticVocabulary": diagnostic_vocabulary(),
        "interpretationBoundaries": [
            "similarity and correlation are advisory, not causal proof",
            "no automatic workflow rerun",
            "no automatic issue, priority, or durable-knowledge mutation",
            "knowledge candidates require human acceptance",
        ],
    }


def write_output(directory: Path, report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if directory.is_symlink():
        raise AppError(f"refusing symlink output directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    payloads = {
        "actions-report.json": json_bytes(report),
        "actions-report.md": render_markdown(report).encode(),
        "families.json": json_bytes({
            "schemaVersion": OUTPUT_SCHEMA_VERSION,
            "families": report["families"],
            "systemicFamilies": report["systemicFamilies"],
        }),
        "lessons-candidates.json": json_bytes({
            "schemaVersion": OUTPUT_SCHEMA_VERSION,
            "policyVersion": KNOWLEDGE_CANDIDATE_POLICY_VERSION,
            "candidates": report["lessonsCandidates"],
        }),
        "diagnostic-vocabulary.json": json_bytes(report["diagnosticVocabulary"]),
    }
    evidence_files = {
        "actions/actions-report.json": payloads["actions-report.json"],
        "actions/families.json": payloads["families.json"],
        "actions/lessons-candidates.json": payloads["lessons-candidates.json"],
        "actions/diagnostic-vocabulary.json": payloads["diagnostic-vocabulary.json"],
    }
    payloads["evidence.dx.txt"] = make_readonly_dx(evidence_files)
    records = {}
    for name, data in payloads.items():
        path = directory / name
        atomic_write(path, data)
        records[name] = {"path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "collectorVersion": PROGRAM_VERSION,
        "artifacts": records,
    }
    manifest_data = json_bytes(manifest)
    atomic_write(directory / "manifest.json", manifest_data)
    records["manifest.json"] = {
        "path": str(directory / "manifest.json"), "size": len(manifest_data),
        "sha256": hashlib.sha256(manifest_data).hexdigest(),
    }
    return records


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", default=[], metavar="OWNER/REPO",
                        help="repository to inspect; repeatable; default is current repository")
    parser.add_argument("--include-submodules", action="store_true",
                        help="also inspect initialized submodule repositories when inferring")
    parser.add_argument("--days", type=float, default=7.0,
                        help="lookback period in days (default: 7)")
    parser.add_argument("--until", help="ISO-8601 end time; default is now")
    parser.add_argument("--conclusion", action="append", choices=sorted(FAILURE_CONCLUSIONS | {"cancelled"}),
                        help="included run conclusion; repeatable")
    parser.add_argument("--threshold", type=float, default=0.62,
                        help="approximate-family threshold from 0 to 1 (default: 0.62)")
    parser.add_argument("--cross-repo", action="store_true",
                        help="allow approximate families to contain multiple repositories")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-evidence-lines", type=int, default=40)
    parser.add_argument("--max-evidence-chars", type=int, default=8000)
    parser.add_argument("--baseline", type=Path,
                        help="previous actions-report.json for new/recurring/resolved comparison")
    parser.add_argument("--out", type=Path, default=Path(".dx/actions-analysis"),
                        help="output directory (default: .dx/actions-analysis)")
    parser.add_argument("--fail-if-found", action="store_true",
                        help="exit 2 when matching failures exist")
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROGRAM_VERSION}")
    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days must be greater than zero")
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.workers < 1 or args.retries < 0:
        parser.error("--workers must be positive and --retries must be non-negative")
    if args.max_evidence_lines < 1 or args.max_evidence_chars < 1:
        parser.error("evidence limits must be positive")
    args.conclusion = set(args.conclusion or ["failure", "timed_out", "startup_failure"])
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        auth = execute(["gh", "auth", "status"], check=False)
        if auth.returncode:
            raise AppError("GitHub CLI is not authenticated; run `gh auth login`")
        repositories = resolve_repositories(args.repo, args.include_submodules)
        until = parse_timestamp(args.until) if args.until else dt.datetime.now(dt.timezone.utc)
        until = until.astimezone(dt.timezone.utc)
        since = until - dt.timedelta(days=args.days)
        all_runs: list[RunObservation] = []
        for repository in repositories:
            all_runs.extend(list_runs(repository, since, until, args.conclusion | {"success"}))
        runs = [run for run in all_runs if run.conclusion in args.conclusion]
        failures: list[FailureObservation] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {
                pool.submit(extract_run_failures, run,
                            max_lines=args.max_evidence_lines,
                            max_chars=args.max_evidence_chars,
                            retries=args.retries,
                            include_cancelled_jobs="cancelled" in args.conclusion): run
                for run in runs
            }
            for future in concurrent.futures.as_completed(pending):
                run = pending[future]
                try:
                    failures.extend(future.result())
                except Exception as exc:
                    print(f"warning: could not analyze {run.repository} run {run.run_id}: {exc}", file=sys.stderr)
                    evidence = normalize_line(str(exc))
                    failures.append(FailureObservation(
                        repository=run.repository, run_id=run.run_id, attempt=run.attempt,
                        run_number=run.run_number, workflow=run.workflow,
                        workflow_path=run.workflow_path, branch=run.branch, event=run.event,
                        commit=run.commit, title=run.title, actor=run.actor,
                        created_at=run.created_at, conclusion=run.conclusion, url=run.url,
                        job_id=None, job="(analysis unavailable)", matrix="", runner_name="",
                        runner_group="", step_number=None, step="(analysis unavailable)",
                        evidence=evidence, evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
                        evidence_retrieval_status="analysis-error",
                        exact_fingerprint=exact_fingerprint(run.workflow, "analysis", "unavailable", evidence),
                    ))
        failures.sort(key=lambda item: (item.created_at, item.repository, item.run_id), reverse=True)
        families = cluster_approximate(failures, args.threshold, args.cross_repo)
        systemic = cluster_systemic(families)
        configuration = {
            "conclusions": sorted(args.conclusion),
            "threshold": args.threshold,
            "crossRepositoryApproximateFamilies": args.cross_repo,
            "similarityModelVersion": SIMILARITY_MODEL_VERSION,
            "knowledgeCandidatePolicyVersion": KNOWLEDGE_CANDIDATE_POLICY_VERSION,
            "maxEvidenceLines": args.max_evidence_lines,
            "maxEvidenceCharacters": args.max_evidence_chars,
            "readOnly": True,
        }
        report = build_report(repositories, since, until, all_runs, failures, families,
                              systemic, args.baseline, configuration)
        report["summary"]["failedRuns"] = len(runs)
        artifacts = write_output(args.out, report)
        print(f"GitHub Actions evidence written to {args.out.resolve()}")
        print(f"Failed runs: {len(runs)}")
        print(f"Failure occurrences: {len(failures)}")
        print(f"Approximate families: {len(families)}")
        print(f"Systemic families: {len(systemic)}")
        print(f"Knowledge candidates: {len(report['lessonsCandidates'])}")
        print("Artifacts:")
        for name in sorted(artifacts):
            record = artifacts[name]
            print(f"- {name}: {record['size']} bytes, SHA-256 {record['sha256']}")
        return 2 if args.fail_if_found and failures else 0
    except (AppError, ValueError) as exc:
        print(f"ERROR [ACTIONS_EVIDENCE_COLLECTION_FAILED]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
