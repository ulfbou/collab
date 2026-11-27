"""Pure classification of the smallest continuation for one pending boundary."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from collab.boundary_contracts import (
    BOUNDARY_SCHEMA,
    ContractResult,
    evaluate_receipt_applicability,
)

CONTINUATION_DECISION_SCHEMA = "collab/continuation-decision/v1"
CLASSIFIER_VERSION = 1
DECISIONS = (
    "EXECUTE_BOUNDARY", "REUSE_RECEIPT", "RESUME_PARTIAL_BOUNDARY",
    "REPAIR_NARROW_FAILURE", "WAIT_FOR_HOSTED_STATE", "REOBSERVE_STATE",
    "REQUEST_EVIDENCE", "REQUEST_DECISION", "REJECT_INCONSISTENT_STATE",
)
_ALLOWED = {
    "boundary", "receipt", "candidateIdentity", "configurationIdentity",
    "validatorIdentity", "missingDomains", "authorityState", "hostedState",
    "observationState", "inconsistencyState", "attemptState",
    "blockedOperations",
}


class ClassificationError(ValueError):
    """Malformed or noncanonical classification input."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ClassificationError("input must be canonical JSON data") from exc


def _closed(value: Any, path: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ClassificationError(f"{path} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ClassificationError(f"{path} contains unsupported properties: {sorted(unknown)}")
    return value


def _set_of_text(value: Any, path: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ClassificationError(f"{path} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ClassificationError(f"{path} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise ClassificationError(f"{path} contains duplicate equivalent input")
    return sorted(value)


def _enum(value: Any, path: str, allowed: set[str], default: str) -> str:
    value = default if value is None else value
    if value not in allowed:
        raise ClassificationError(f"{path} has an unsupported value")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ClassificationError(f"{path} must be a non-empty canonical string")
    return value


def _normalize(source: Mapping[str, Any]) -> dict[str, Any]:
    source = _closed(source, "$", _ALLOWED)
    required = {"boundary", "candidateIdentity", "configurationIdentity", "validatorIdentity"}
    if not required <= set(source):
        raise ClassificationError(f"missing required properties: {sorted(required - set(source))}")
    boundary = source["boundary"]
    if not isinstance(boundary, Mapping) or boundary.get("schema") != BOUNDARY_SCHEMA:
        raise ClassificationError("$.boundary must be an Issue #65 BoundaryDescriptor")
    boundary_id = boundary.get("boundaryId")
    if not isinstance(boundary_id, str) or not boundary_id.startswith("sha256:boundary:v1:"):
        raise ClassificationError("$.boundary.boundaryId must be canonical")
    receipt = source.get("receipt")
    if receipt is not None and not isinstance(receipt, Mapping):
        raise ClassificationError("$.receipt must be an Issue #65 Receipt")
    normalized = {
        "boundary": boundary,
        "receipt": receipt,
        "candidateIdentity": _text(source["candidateIdentity"], "$.candidateIdentity"),
        "configurationIdentity": _text(source["configurationIdentity"], "$.configurationIdentity"),
        "validatorIdentity": _text(source["validatorIdentity"], "$.validatorIdentity"),
        "missingDomains": _set_of_text(source.get("missingDomains", ()), "$.missingDomains"),
        "authorityState": _enum(source.get("authorityState"), "$.authorityState", {"AVAILABLE", "RESERVED", "CONFLICTING"}, "AVAILABLE"),
        "hostedState": _enum(source.get("hostedState"), "$.hostedState", {"COMPLETE", "INCOMPLETE", "CONFLICTING"}, "COMPLETE"),
        "observationState": _enum(source.get("observationState"), "$.observationState", {"CURRENT", "STALE_RECOVERABLE", "CONFLICTING"}, "CURRENT"),
        "inconsistencyState": _enum(source.get("inconsistencyState"), "$.inconsistencyState", {"NONE", "RECOVERABLE", "IRRECONCILABLE"}, "NONE"),
        "attemptState": _enum(source.get("attemptState"), "$.attemptState", {"NONE", "PARTIAL", "NARROW_FAILURE"}, "NONE"),
        "blockedOperations": _set_of_text(source.get("blockedOperations", ()), "$.blockedOperations"),
    }
    _canonical(normalized)
    return normalized


def _diagnostic(code: str, path: str, message: str, domains: Sequence[str] = ()) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message, "domains": sorted(domains)}


def _evaluate(value: Mapping[str, Any]) -> tuple[dict[str, Any], ContractResult | None]:
    receipt = value["receipt"]
    if receipt is None:
        return {"receiptPresent": False, "evaluated": False, "applicable": False, "invalidators": []}, None
    result = evaluate_receipt_applicability(
        receipt,
        boundary=value["boundary"],
        candidate_identity=value["candidateIdentity"],
        configuration_identity=value["configurationIdentity"],
        validator_identity=value["validatorIdentity"],
    )
    if not result.valid or not isinstance(result.value, Mapping):
        detail = result.diagnostics[0] if result.diagnostics else {}
        raise ClassificationError(f"invalid Issue #65 receipt evidence: {detail.get('code', 'unknown')}")
    invalidators = [dict(item) for item in result.value["invalidators"]]
    return {
        "receiptPresent": True,
        "evaluated": True,
        "applicable": bool(result.value["applicable"]),
        "invalidators": invalidators,
    }, result


def classify_continuation(source: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one boundary without mutating predecessor evidence or performing I/O."""
    value = _normalize(source)
    applicability, _ = _evaluate(value)
    diagnostics: list[dict[str, Any]] = []
    conflicts = sorted(name for name, state in (
        ("authority", value["authorityState"]),
        ("hosted", value["hostedState"]),
        ("observation", value["observationState"]),
    ) if state == "CONFLICTING")

    if value["missingDomains"]:
        decision = "REQUEST_EVIDENCE"
        diagnostics.append(_diagnostic("missing_evidence", "$.missingDomains", "Required evidence domains are missing", value["missingDomains"]))
    elif value["inconsistencyState"] == "IRRECONCILABLE":
        decision = "REJECT_INCONSISTENT_STATE"
        diagnostics.append(_diagnostic("irreconcilable_state", "$.inconsistencyState", "Evidence explicitly establishes an irreconcilable inconsistency", conflicts or ("state",)))
    elif conflicts or value["inconsistencyState"] == "RECOVERABLE":
        decision = "REOBSERVE_STATE"
        diagnostics.append(_diagnostic("recoverable_inconsistency", "$", "Inconsistent evidence can be refreshed without replacing the boundary", conflicts or ("state",)))
    elif value["authorityState"] == "RESERVED":
        decision = "REQUEST_DECISION"
        diagnostics.append(_diagnostic("reserved_human_authority", "$.authorityState", "The pending boundary requires reserved human authority", ("authority",)))
    elif value["hostedState"] == "INCOMPLETE":
        decision = "WAIT_FOR_HOSTED_STATE"
        diagnostics.append(_diagnostic("hosted_state_incomplete", "$.hostedState", "Hosted evidence is not complete", ("hosted",)))
    elif value["observationState"] == "STALE_RECOVERABLE":
        decision = "REOBSERVE_STATE"
        diagnostics.append(_diagnostic("observation_stale", "$.observationState", "Observed state can be safely refreshed", ("observation",)))
    elif value["attemptState"] == "PARTIAL":
        decision = "RESUME_PARTIAL_BOUNDARY"
        diagnostics.append(_diagnostic("partial_boundary", "$.attemptState", "Resume only the identified incomplete portion"))
    elif value["attemptState"] == "NARROW_FAILURE":
        decision = "REPAIR_NARROW_FAILURE"
        diagnostics.append(_diagnostic("narrow_failure", "$.attemptState", "Repair only the classified narrow failure"))
    elif applicability["applicable"]:
        decision = "REUSE_RECEIPT"
        diagnostics.append(_diagnostic("receipt_applicable", "$.receipt", "Issue #65 receipt applicability is valid"))
    else:
        decision = "EXECUTE_BOUNDARY"
        if value["receipt"] is None:
            diagnostics.append(_diagnostic("no_reusable_receipt", "$.receipt", "No Issue #65 receipt is available"))
        else:
            domains = [item["field"] for item in applicability["invalidators"]]
            diagnostics.append(_diagnostic("receipt_not_applicable", "$.receipt", "Issue #65 receipt applicability has invalidators", domains))

    identity_input = {"classifierVersion": CLASSIFIER_VERSION, **value}
    classifier_identity = "sha256:continuation:v1:" + hashlib.sha256(_canonical(identity_input)).hexdigest()
    return {
        "schema": CONTINUATION_DECISION_SCHEMA,
        "classifierVersion": CLASSIFIER_VERSION,
        "classifierIdentity": classifier_identity,
        "boundaryIdentity": value["boundary"]["boundaryId"],
        "decision": decision,
        "valid": True,
        "blockedOperations": value["blockedOperations"],
        "missingDomains": value["missingDomains"] if decision == "REQUEST_EVIDENCE" else [],
        "applicability": applicability,
        "diagnostics": diagnostics,
    }
