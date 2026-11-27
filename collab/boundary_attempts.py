"""Pure construction of immutable BoundaryAttempt values."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from collab.boundary_contracts import evaluate_receipt_applicability

SCHEMA = "collab/boundary-attempt/v1"
NORMALIZATION_VERSION = "1"
STATUSES = frozenset({"COMPLETED", "FAILED", "NOT_ATTEMPTED"})
FAILURE_OWNERS = frozenset({"CANDIDATE", "WORKFLOW", "ENVIRONMENT", "AUTHORITY", "CONSISTENCY"})
BOUNDARY_ID = re.compile(r"^sha256:boundary:v1:[0-9a-f]{64}$")
RECEIPT_ID = re.compile(r"^sha256:receipt:v1:[0-9a-f]{64}$")
IDENTITY = re.compile(r"^sha256:(?:[a-z][a-z0-9-]*:v1:)?[0-9a-f]{64}$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def serialize_boundary_attempt(value: Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 bytes for an already constructed attempt."""
    return _canonical(_plain(value))


def create_boundary_attempt(*, boundary: Mapping[str, Any], operation_plan: Sequence[str], operation_plan_authority: Mapping[str, bool], operations: Sequence[Mapping[str, Any]], receipts: Sequence[Mapping[str, Any]] = (), applicability_context: Mapping[str, str]) -> Mapping[str, Any]:
    """Validate and construct one immutable BoundaryAttempt; raise ValueError on malformed input."""
    if not isinstance(boundary, Mapping) or boundary.get("schema") != "collab/boundary-descriptor/v1":
        raise ValueError("exactly one valid Boundary is required")
    boundary_id = boundary.get("boundaryId")
    if not isinstance(boundary_id, str) or not BOUNDARY_ID.fullmatch(boundary_id):
        raise ValueError("boundary identity is malformed")
    if isinstance(operation_plan, (str, bytes)) or not isinstance(operation_plan, Sequence) or not operation_plan:
        raise ValueError("operation plan must be a non-empty sequence")
    plan = list(operation_plan)
    if any(not isinstance(x, str) or not x.strip() for x in plan) or len(set(plan)) != len(plan):
        raise ValueError("operation plan IDs must be unique non-empty strings")
    authority_keys = {"completenessEstablished", "scopeConformityEstablished"}
    if not isinstance(operation_plan_authority, Mapping) or set(operation_plan_authority) != authority_keys:
        raise ValueError("operation plan authority must be a complete closed assertion")
    if any(type(operation_plan_authority[key]) is not bool for key in authority_keys):
        raise ValueError("operation plan authority assertions must be boolean")
    if not all(operation_plan_authority[key] is True for key in authority_keys):
        raise ValueError("operation plan completeness and scope conformity must be established")
    operation_plan_identity = "sha256:operation-plan:v1:" + hashlib.sha256(_canonical(plan)).hexdigest()
    if isinstance(operations, (str, bytes)) or not isinstance(operations, Sequence) or len(operations) != len(plan):
        raise ValueError("operations must exactly cover the authoritative plan")
    context_keys = {"candidateIdentity", "configurationIdentity", "validatorIdentity"}
    if not isinstance(applicability_context, Mapping) or set(applicability_context) != context_keys:
        raise ValueError("applicability context must be complete and closed")
    if any(not isinstance(applicability_context[k], str) or not IDENTITY.fullmatch(applicability_context[k]) for k in context_keys):
        raise ValueError("applicability context identity is malformed")

    receipt_by_id: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ValueError("receipt must be a mapping")
        rid = receipt.get("receiptId")
        if not isinstance(rid, str) or not RECEIPT_ID.fullmatch(rid) or rid in receipt_by_id:
            raise ValueError("receipt identities must be canonical and unique")
        receipt_by_id[rid] = receipt

    normalized_ops = []
    failed_index = None
    seen_receipts: set[str] = set()
    for index, (expected, supplied) in enumerate(zip(plan, operations)):
        if not isinstance(supplied, Mapping):
            raise ValueError("operation must be a mapping")
        allowed = {"operationId", "ordinal", "status", "receiptIds", "failure"}
        if set(supplied) - allowed:
            raise ValueError("unknown operation property")
        if supplied.get("operationId") != expected or supplied.get("ordinal") != index:
            raise ValueError("operation order contradicts the authoritative plan")
        status = supplied.get("status")
        if status not in STATUSES:
            raise ValueError("unknown operation status")
        ids = supplied.get("receiptIds", [])
        if isinstance(ids, (str, bytes)) or not isinstance(ids, Sequence) or len(set(ids)) != len(ids):
            raise ValueError("receiptIds must be a unique sequence")
        if any(rid not in receipt_by_id for rid in ids) or seen_receipts.intersection(ids):
            raise ValueError("receipt association must reference each supplied receipt at most once")
        seen_receipts.update(ids)
        failure = supplied.get("failure")
        if status == "FAILED":
            if failed_index is not None or not isinstance(failure, Mapping):
                raise ValueError("exactly one explicit failure is allowed")
            if set(failure) - {"code", "owner", "operationId", "message"}:
                raise ValueError("unknown failure property")
            if failure.get("operationId") != expected or failure.get("owner") not in FAILURE_OWNERS:
                raise ValueError("failure owner and operation must be explicit")
            if not isinstance(failure.get("code"), str) or not CODE.fullmatch(failure["code"]):
                raise ValueError("failure code must be stable and machine-readable")
            if "message" in failure and not isinstance(failure["message"], str):
                raise ValueError("failure message must be text")
            failed_index = index
        elif failure is not None:
            raise ValueError("failure is allowed only on FAILED")
        normalized = {"operationId": expected, "ordinal": index, "status": status, "receiptIds": list(ids)}
        if failure is not None:
            normalized["failure"] = copy.deepcopy(dict(failure))
        normalized_ops.append(normalized)

    statuses = [x["status"] for x in normalized_ops]
    if failed_index is not None:
        if statuses[:failed_index] != ["COMPLETED"] * failed_index or statuses[failed_index + 1:] != ["NOT_ATTEMPTED"] * (len(statuses) - failed_index - 1):
            raise ValueError("contradictory status sequence around failure")
    else:
        seen_not = False
        for status in statuses:
            if status == "FAILED":
                raise ValueError("failure mismatch")
            if status == "NOT_ATTEMPTED":
                seen_not = True
            elif seen_not:
                raise ValueError("completed operation follows not-attempted operation")

    conclusions = []
    for op in normalized_ops:
        for rid in op["receiptIds"]:
            result = evaluate_receipt_applicability(
                receipt_by_id[rid], boundary=boundary,
                candidate_identity=applicability_context["candidateIdentity"],
                configuration_identity=applicability_context["configurationIdentity"],
                validator_identity=applicability_context["validatorIdentity"],
            )
            if not result.valid or result.value is None:
                raise ValueError("authoritative receipt applicability evaluation failed")
            conclusions.append({"operationId": op["operationId"], **copy.deepcopy(dict(result.value))})
    resume = plan[failed_index] if failed_index is not None else next((op["operationId"] for op in normalized_ops if op["status"] == "NOT_ATTEMPTED"), None)
    owner = normalized_ops[failed_index]["failure"]["owner"] if failed_index is not None else None
    material = {
        "schema": SCHEMA,
        "normalizationVersion": NORMALIZATION_VERSION,
        "boundaryIdentity": boundary_id,
        "operationPlanIdentity": operation_plan_identity,
        "operationPlanAuthority": copy.deepcopy(dict(operation_plan_authority)),
        "operationPlan": plan,
        "operations": normalized_ops,
        "applicabilityContext": copy.deepcopy(dict(applicability_context)),
        "receiptConclusions": conclusions,
        "resumeOperationId": resume,
        "automaticContinuationAllowed": not (owner in {"AUTHORITY", "CONSISTENCY"}),
    }
    attempt_id = "sha256:boundary-attempt:v1:" + hashlib.sha256(_canonical(material)).hexdigest()
    return _freeze({**material, "attemptId": attempt_id})