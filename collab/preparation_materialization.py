"""Deterministic materialization of one accepted PreparationPlan.

This module is deliberately narrower than a packaging framework. It renders
immutable bytes only; publishing those bytes is a separate filesystem action.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .preparation_planning import PLAN_SCHEMA

PACKAGE_SCHEMA = "collab/development-chat-package/v1"
MAX_OPERATOR_ARTIFACTS = 3


@dataclass(frozen=True)
class MaterializationResult:
    status: str
    artifacts: tuple[tuple[str, bytes], ...]
    diagnostics: tuple[Mapping[str, str], ...]

    @property
    def valid(self) -> bool:
        return self.status == "complete" and bool(self.artifacts)

    def as_mapping(self) -> Mapping[str, bytes]:
        return dict(self.artifacts)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _invalid(code: str, path: str, message: str) -> MaterializationResult:
    return MaterializationResult("invalid", (), ({"code": code, "path": path, "message": message},))


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _validate_plan(plan: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    if plan.get("schema") != PLAN_SCHEMA:
        return "invalid_plan", "$.schema", "unsupported preparation plan schema"
    supplied_id = _text(plan.get("planId"))
    if not supplied_id:
        return "invalid_plan", "$.planId", "planId is required"
    core = copy.deepcopy(dict(plan)); core.pop("planId", None)
    expected = "sha256:preparation-plan:v1:" + hashlib.sha256(_canonical(core)).hexdigest()
    if supplied_id != expected:
        return "inapplicable_plan", "$.planId", "plan identity does not match normalized plan"
    boundary = plan.get("boundary")
    if not isinstance(boundary, Mapping):
        return "invalid_boundary", "$.boundary", "exactly one boundary object is required"
    if not _text(boundary.get("boundaryId")) or boundary.get("status") != "pending":
        return "non_pending_boundary", "$.boundary", "the sole boundary must be pending"
    selection = plan.get("selection")
    if selection not in ("STATE_ONLY", "FOCUSED", "BROAD", "EXPLICIT_FULL"):
        return "invalid_plan", "$.selection", "unsupported selection mode"
    selected = plan.get("selectedItems")
    if not isinstance(selected, list):
        return "invalid_plan", "$.selectedItems", "selectedItems must be an array"
    ids: set[str] = set()
    for index, item in enumerate(selected):
        if not isinstance(item, Mapping):
            return "invalid_plan", f"$.selectedItems[{index}]", "selected item must be an object"
        item_id = _text(item.get("itemId")); domain = _text(item.get("domain")); reason = _text(item.get("reasonCode"))
        byte_size = item.get("byteSize"); artifact_count = item.get("artifactCount")
        if not item_id or not domain or not reason or item_id in ids:
            return "invalid_plan", f"$.selectedItems[{index}]", "each selected item needs a unique identity, domain, and one reason code"
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
            return "invalid_plan", f"$.selectedItems[{index}].byteSize", "selected item byteSize must be a non-negative integer"
        if not isinstance(artifact_count, int) or isinstance(artifact_count, bool) or artifact_count < 0:
            return "invalid_plan", f"$.selectedItems[{index}].artifactCount", "selected item artifactCount must be a non-negative integer"
        ids.add(item_id)
    limits = plan.get("limits")
    if not isinstance(limits, Mapping) or not isinstance(limits.get("bytes"), int) or isinstance(limits.get("bytes"), bool) or not isinstance(limits.get("artifacts"), int) or isinstance(limits.get("artifacts"), bool):
        return "invalid_plan", "$.limits", "integer byte and artifact limits are required"
    if limits["bytes"] <= 0 or limits["artifacts"] <= 0 or limits["artifacts"] > MAX_OPERATOR_ARTIFACTS:
        return "invalid_plan", "$.limits", "limits must allow one to three artifacts and positive bytes"
    sentinel = plan.get("mutationSentinel")
    expected_sentinel = {"writesPerformed": False, "boundaryAdvanced": False, "packageMaterialized": False}
    if sentinel != expected_sentinel:
        return "mutation_boundary_violation", "$.mutationSentinel", "planning mutation sentinel is not pristine"
    domains = plan.get("requiredDomains")
    limitations = plan.get("limitations")
    omissions = plan.get("omissions")
    totals = plan.get("totals")
    if not isinstance(domains, list) or not isinstance(limitations, list) or not isinstance(omissions, list):
        return "invalid_plan", "$.requiredDomains", "domain status, limitations, and omissions arrays are required"
    limited_domains: set[str] = set()
    for index, limitation in enumerate(limitations):
        if not isinstance(limitation, Mapping) or not _text(limitation.get("domain")) or not _text(limitation.get("code")):
            return "invalid_plan", f"$.limitations[{index}]", "limitation needs a domain and code"
        if limitation["code"] == "required-domain-incomplete":
            limited_domains.add(limitation["domain"])
    domain_names: set[str] = set()
    for index, domain in enumerate(domains):
        name = _text(domain.get("domain")) if isinstance(domain, Mapping) else None
        if not name or name in domain_names or domain.get("status") not in ("complete", "limited"):
            return "invalid_plan", f"$.requiredDomains[{index}]", "required domains need unique identities and valid status"
        domain_names.add(name)
        if domain["status"] == "limited" and name not in limited_domains:
            return "missing_domain_disclosure", f"$.requiredDomains[{index}]", "limited domain lacks explicit limitation"
    omission_ids: set[str] = set()
    for index, omission in enumerate(omissions):
        item_id = _text(omission.get("itemId")) if isinstance(omission, Mapping) else None
        reason = _text(omission.get("reasonCode")) if isinstance(omission, Mapping) else None
        if not item_id or not reason or item_id in omission_ids:
            return "invalid_plan", f"$.omissions[{index}]", "omissions need unique item identities and reason codes"
        omission_ids.add(item_id)
    if not isinstance(totals, Mapping):
        return "invalid_plan", "$.totals", "totals object is required"
    total_bytes = totals.get("bytes"); total_artifacts = totals.get("artifacts")
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool) or total_bytes < 0 or not isinstance(total_artifacts, int) or isinstance(total_artifacts, bool) or total_artifacts < 0:
        return "invalid_plan", "$.totals", "totals must contain non-negative integer bytes and artifacts"
    if total_bytes != sum(item["byteSize"] for item in selected) or total_artifacts != sum(item["artifactCount"] for item in selected):
        return "invalid_plan", "$.totals", "totals do not match selected evidence"
    return None, None, None


def _decode_declarations(data: bytes, path: str) -> tuple[dict[str, str] | None, MaterializationResult | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, _invalid("invalid_member", path, "package member must be UTF-8")
    declarations: dict[str, str] = {}
    prefixes = {
        "Package input binding: ": "inputBinding",
        "Preparation plan: ": "planId",
        "Pending boundary: ": "boundaryId",
        "PACKAGE INPUT BINDING: ": "inputBinding",
        "PACKAGE PLAN ID: ": "planId",
        "PACKAGE BOUNDARY ID: ": "boundaryId",
    }
    for line in text.splitlines():
        for prefix, key in prefixes.items():
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if key in declarations and declarations[key] != value:
                    return None, _invalid("member_binding", path, f"conflicting {key} declaration")
                declarations[key] = value
    return declarations, None


def validate_materialized_package(artifacts: Mapping[str, bytes]) -> MaterializationResult:
    """Detect stale, mixed, altered, or over-broad package members."""
    if not isinstance(artifacts, Mapping) or not 2 <= len(artifacts) <= MAX_OPERATOR_ARTIFACTS:
        return _invalid("artifact_count", "$", "package must contain two or three artifacts")
    allowed = {"project.current-state.json", "project.context.txt", "project.context.dx.txt", "project.start-prompt.txt"}
    if not set(artifacts).issubset(allowed) or "project.current-state.json" not in artifacts or "project.start-prompt.txt" not in artifacts:
        return _invalid("artifact_set", "$", "package contains an unexpected or missing artifact")
    if any(not isinstance(value, bytes) for value in artifacts.values()):
        return _invalid("invalid_member", "$", "package members must be bytes")
    try:
        manifest = json.loads(artifacts["project.current-state.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _invalid("invalid_manifest", "$.project.current-state.json", "manifest is not canonical UTF-8 JSON")
    if not isinstance(manifest, Mapping) or manifest.get("schema") != PACKAGE_SCHEMA:
        return _invalid("invalid_manifest", "$.schema", "unsupported package schema")
    plan_id = _text(manifest.get("planId")); binding = _text(manifest.get("inputBinding")); boundary = manifest.get("boundary")
    boundary_id = _text(boundary.get("boundaryId")) if isinstance(boundary, Mapping) else None
    if not plan_id or not binding or not boundary_id:
        return _invalid("invalid_manifest", "$", "manifest identities are incomplete")
    members = manifest.get("members")
    expected_names = sorted(k for k in artifacts if k != "project.current-state.json")
    if not isinstance(members, list) or any(not isinstance(m, Mapping) for m in members) or [m.get("name") for m in members] != expected_names:
        return _invalid("member_identity", "$.members", "manifest member set or order does not match package")
    for member in members:
        name = member["name"]
        if member.get("sha256") != _digest(artifacts[name]) or member.get("bytes") != len(artifacts[name]):
            return _invalid("member_identity", f"$.members.{name}", "package member is stale, mixed, or altered")
    if manifest.get("artifactCount") != len(artifacts):
        return _invalid("artifact_count", "$.artifactCount", "manifest artifact count does not match package")
    prompt_declarations, error = _decode_declarations(artifacts["project.start-prompt.txt"], "$.project.start-prompt.txt")
    if error:
        return error
    assert prompt_declarations is not None
    expected = {"inputBinding": binding, "planId": plan_id, "boundaryId": boundary_id}
    if any(prompt_declarations.get(key) != value for key, value in expected.items()):
        return _invalid("member_binding", "$.project.start-prompt.txt", "prompt declarations do not match manifest identities")
    context_names = [name for name in artifacts if name.startswith("project.context.")]
    if context_names:
        context_declarations, error = _decode_declarations(artifacts[context_names[0]], f"$.{context_names[0]}")
        if error:
            return error
        assert context_declarations is not None
        if any(context_declarations.get(key) != value for key, value in expected.items()):
            return _invalid("member_binding", f"$.{context_names[0]}", "context declarations do not match manifest identities")
    return MaterializationResult("complete", tuple(sorted(artifacts.items())), ())


def materialize_preparation_plan(
    plan: Mapping[str, Any],
    evidence_payloads: Mapping[str, str | bytes],
    assignment: Mapping[str, Any],
) -> MaterializationResult:
    """Render immutable operator-facing bytes from one accepted plan.

    ``assignment`` supplies presentation data absent from the planning contract:
    activeCard, establishedState, developmentIntent, authorities,
    resultContract, and stopCondition.
    """
    plan_source = copy.deepcopy(plan); payload_source = copy.deepcopy(evidence_payloads); assignment_source = copy.deepcopy(assignment)
    if not isinstance(plan_source, Mapping):
        return _invalid("invalid_plan", "$", "plan must be an object")
    code, path, message = _validate_plan(plan_source)
    if code:
        return _invalid(code, path or "$", message or "invalid plan")
    required_assignment = ("activeCard", "establishedState", "developmentIntent", "authorities", "resultContract", "stopCondition")
    for key in required_assignment:
        if key == "authorities":
            if not isinstance(assignment_source.get(key), list) or not assignment_source[key]:
                return _invalid("incomplete_assignment", f"$.assignment.{key}", "non-empty authorities are required")
        elif not _text(assignment_source.get(key)):
            return _invalid("incomplete_assignment", f"$.assignment.{key}", f"{key} is required")
    selected = plan_source["selectedItems"]
    expected_ids = [item["itemId"] for item in selected]
    if set(payload_source) != set(expected_ids):
        return _invalid("evidence_mismatch", "$.evidencePayloads", "payload identities must exactly match selected evidence")
    normalized_payloads: list[dict[str, Any]] = []
    for item in sorted(selected, key=lambda x: x["itemId"]):
        raw = payload_source[item["itemId"]]
        if isinstance(raw, str): data = raw.encode("utf-8")
        elif isinstance(raw, bytes): data = raw
        else: return _invalid("invalid_evidence", f"$.evidencePayloads.{item['itemId']}", "payload must be text or bytes")
        if len(data) != item.get("byteSize"):
            return _invalid("evidence_mismatch", f"$.evidencePayloads.{item['itemId']}", "payload byte size differs from accepted plan")
        normalized_payloads.append({"itemId": item["itemId"], "domain": item["domain"], "reasonCode": item["reasonCode"], "bytes": len(data), "sha256": _digest(data), "data": data})
    normalized = {"plan": plan_source, "assignment": assignment_source, "evidence": [{k: v for k, v in p.items() if k != "data"} for p in normalized_payloads]}
    binding = _digest(_canonical(normalized))
    context_name = None
    context_bytes = None
    if plan_source["selection"] != "STATE_ONLY":
        context_name = "project.context.txt"
        sections = []
        for payload in normalized_payloads:
            try: rendered = payload["data"].decode("utf-8")
            except UnicodeDecodeError: return _invalid("invalid_evidence", f"$.evidencePayloads.{payload['itemId']}", "context payload must be UTF-8")
            sections.append(f"=== {payload['itemId']} | {payload['domain']} | {payload['reasonCode']} ===\n{rendered.rstrip()}\n")
        context_bytes = ("PACKAGE INPUT BINDING: " + binding + "\n" +
                         "PACKAGE PLAN ID: " + plan_source["planId"] + "\n" +
                         "PACKAGE BOUNDARY ID: " + plan_source["boundary"]["boundaryId"] + "\n\n" +
                         "\n".join(sections)).encode("utf-8")
    def render_list(values: Any) -> str:
        return "\n".join(f"- {value}" for value in values) if values else "- none"
    prompt = f"""DEVELOPMENT CHAT PACKAGE
Package input binding: {binding}
Preparation plan: {plan_source['planId']}
Pending boundary: {plan_source['boundary']['boundaryId']}

ACTIVE CARD
{assignment_source['activeCard']}

ESTABLISHED STATE
{assignment_source['establishedState']}

SOLE DEVELOPMENT INTENT
{assignment_source['developmentIntent']}

APPLICABLE AUTHORITIES
{render_list(assignment_source['authorities'])}

ONE PENDING BOUNDARY
{plan_source['boundary']['boundaryId']} (pending)

SUPPLIED EVIDENCE
{render_list([f"{p['itemId']} [{p['reasonCode']}] {p['sha256']}" for p in normalized_payloads])}

OMISSIONS
{render_list([f"{x.get('itemId')} [{x.get('reasonCode')}]" for x in plan_source.get('omissions', [])])}

LIMITATIONS AND MISSING DOMAINS
{render_list([f"{x.get('domain')} [{x.get('code')}]" for x in plan_source.get('limitations', [])])}

REQUIRED RESULT CONTRACT
{assignment_source['resultContract']}

MUTATION SENTINEL
Do not execute, complete, accept, publish, integrate, synchronize, clean up, or otherwise advance the pending boundary. Do not mutate repository or hosted state.

STOP CONDITION
{assignment_source['stopCondition']}
""".encode("utf-8")
    members: list[tuple[str, bytes]] = [("project.start-prompt.txt", prompt)]
    if context_name and context_bytes is not None: members.append((context_name, context_bytes))
    members.sort()
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "planId": plan_source["planId"],
        "inputBinding": binding,
        "boundary": copy.deepcopy(plan_source["boundary"]),
        "selection": plan_source["selection"],
        "selectedEvidence": [{k: v for k, v in p.items() if k != "data"} for p in normalized_payloads],
        "requiredDomains": copy.deepcopy(plan_source["requiredDomains"]),
        "omissions": copy.deepcopy(plan_source.get("omissions", [])),
        "limitations": copy.deepcopy(plan_source.get("limitations", [])),
        "mutationSentinel": {"repositoryMutated": False, "hostedStateMutated": False, "boundaryExecuted": False, "boundaryAdvanced": False},
        "members": [{"name": name, "bytes": len(data), "sha256": _digest(data)} for name, data in members],
        "artifactCount": len(members) + 1,
    }
    artifacts = tuple(sorted([("project.current-state.json", _pretty(manifest)), *members]))
    total_bytes = sum(len(data) for _, data in artifacts)
    if len(artifacts) > min(MAX_OPERATOR_ARTIFACTS, plan_source["limits"]["artifacts"]):
        return _invalid("artifact_limit", "$.limits.artifacts", "materialized package exceeds artifact limit")
    if total_bytes > plan_source["limits"]["bytes"]:
        return _invalid("byte_limit", "$.limits.bytes", "materialized package exceeds byte limit")
    checked = validate_materialized_package(dict(artifacts))
    return artifacts and MaterializationResult("complete", artifacts, checked.diagnostics) if checked.valid else checked
