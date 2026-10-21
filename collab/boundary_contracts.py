"""Pure construction and applicability contracts for Collab boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

BOUNDARY_SCHEMA = "collab/boundary-descriptor/v1"
RECEIPT_SCHEMA = "collab/receipt/v1"
TRANSITION_SCHEMA = "collab/state-transition/v1"
NORMALIZATION_VERSION = "1"
IDENTITY_PATTERN = re.compile(
    r"^sha256:(?:[a-z][a-z0-9-]*:v1:)?[0-9a-f]{64}$"
)
BOUNDARY_ID_PATTERN = re.compile(
    r"^sha256:boundary:v1:[0-9a-f]{64}$"
)
RECEIPT_ID_PATTERN = re.compile(
    r"^sha256:receipt:v1:[0-9a-f]{64}$"
)


@dataclass(frozen=True)
class ContractResult:
    status: str
    value: Mapping[str, Any] | None
    diagnostics: tuple[Mapping[str, str], ...]

    @property
    def valid(self) -> bool:
        return self.status == "valid"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identity(domain: str, value: Any) -> str | None:
    try:
        digest = hashlib.sha256(_canonical(value)).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return None
    return f"sha256:{domain}:v1:{digest}"


def _invalid(
    code: str,
    path: str,
    message: str,
) -> ContractResult:
    return ContractResult(
        "invalid",
        None,
        (
            {
                "code": code,
                "path": path,
                "message": message,
            },
        ),
    )


def _text(value: Any) -> str | None:
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else None
    )


def _identity_value(value: Any) -> str | None:
    text = _text(value)
    return (
        text
        if text and IDENTITY_PATTERN.fullmatch(text)
        else None
    )


def _texts(
    value: Any,
    *,
    allow_empty: bool = False,
) -> list[str] | None:
    """Normalize and sort unique strings; reject duplicates explicitly."""
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return None

    if any(_text(item) is None for item in value):
        return None

    normalized = [item.strip() for item in value]

    if len(normalized) != len(set(normalized)):
        return None

    result = sorted(normalized)
    return result if result or allow_empty else None


def _identities(
    value: Any,
    *,
    allow_empty: bool = False,
    receipt_only: bool = False,
) -> list[str] | None:
    items = _texts(value, allow_empty=allow_empty)

    if items is None:
        return None

    pattern = (
        RECEIPT_ID_PATTERN
        if receipt_only
        else IDENTITY_PATTERN
    )

    return (
        items
        if all(pattern.fullmatch(item) for item in items)
        else None
    )


def create_boundary_descriptor(
    *,
    responsibility: str,
    scope: Sequence[str],
    identities: Mapping[str, str],
    limitations: Sequence[str] = (),
) -> ContractResult:
    """Construct one pending responsibility without executing it."""
    responsibility_value = _text(responsibility)
    scope_value = _texts(scope)
    limitation_values = _texts(
        limitations,
        allow_empty=True,
    )
    required = {
        "baseline",
        "configuration",
        "validator",
        "state",
        "intent",
        "authority",
        "obligation",
        "subject",
    }

    if responsibility_value is None:
        return _invalid(
            "invalid_responsibility",
            "$.responsibility",
            "Exactly one non-empty responsibility is required",
        )

    if scope_value is None:
        return _invalid(
            "invalid_scope",
            "$.scope",
            "Boundary scope must be non-empty",
        )

    if (
        not isinstance(identities, Mapping)
        or set(identities) != required
    ):
        return _invalid(
            "invalid_identities",
            "$.identities",
            "Boundary identities must match the required identity set",
        )

    normalized_identities = {
        name: _identity_value(identities[name])
        for name in sorted(required)
    }

    if any(
        value is None
        for value in normalized_identities.values()
    ):
        return _invalid(
            "invalid_identity",
            "$.identities",
            "Every boundary identity must be explicit",
        )

    if limitation_values is None:
        return _invalid(
            "invalid_limitations",
            "$.limitations",
            "Limitations must be strings",
        )

    material = {
        "schema": BOUNDARY_SCHEMA,
        "normalizationVersion": NORMALIZATION_VERSION,
        "responsibility": responsibility_value,
        "scope": scope_value,
        "identities": normalized_identities,
        "limitations": limitation_values,
        "executionState": "pending",
    }

    boundary_id = _identity("boundary", material)

    if boundary_id is None:
        return _invalid(
            "non_canonical_boundary",
            "$",
            "Boundary material must be canonically serializable",
        )

    return ContractResult(
        "valid",
        {
            **material,
            "boundaryId": boundary_id,
        },
        (),
    )


def issue_receipt(
    boundary: Mapping[str, Any],
    *,
    candidate_identity: str,
    mutation_identity: str,
    completion_identity: str,
    evidence_identities: Sequence[str],
    limitations: Sequence[str] = (),
) -> ContractResult:
    """Create immutable evidence of completion; do not accept the result."""
    if (
        not isinstance(boundary, Mapping)
        or boundary.get("schema") != BOUNDARY_SCHEMA
    ):
        return _invalid(
            "invalid_boundary",
            "$.boundary",
            "A valid BoundaryDescriptor is required",
        )

    boundary_id = _text(boundary.get("boundaryId"))
    scope = _texts(boundary.get("scope"))

    if (
        boundary_id is None
        or not BOUNDARY_ID_PATTERN.fullmatch(boundary_id)
        or scope is None
    ):
        return _invalid(
            "invalid_boundary",
            "$.boundary",
            "Boundary identity and scope must match the "
            "BoundaryDescriptor contract",
        )

    candidate = _identity_value(candidate_identity)
    mutation = _identity_value(mutation_identity)
    completion = _identity_value(completion_identity)
    evidence = _identities(evidence_identities)
    limitation_values = _texts(
        limitations,
        allow_empty=True,
    )

    if (
        None in (candidate, mutation, completion)
        or evidence is None
        or limitation_values is None
    ):
        return _invalid(
            "invalid_receipt_input",
            "$",
            "Receipt identities and evidence must be explicit",
        )

    ids = boundary.get("identities")

    if not isinstance(ids, Mapping):
        return _invalid(
            "invalid_boundary_identities",
            "$.boundary.identities",
            "Boundary identities must be a mapping",
        )

    applicability = {
        name: _identity_value(ids.get(name))
        for name in (
            "baseline",
            "configuration",
            "validator",
            "state",
            "intent",
            "authority",
            "obligation",
            "subject",
        )
    }

    if any(
        value is None
        for value in applicability.values()
    ):
        return _invalid(
            "invalid_boundary_identities",
            "$.boundary.identities",
            "Boundary applicability identities are invalid",
        )

    material = {
        "schema": RECEIPT_SCHEMA,
        "normalizationVersion": NORMALIZATION_VERSION,
        "boundaryId": boundary_id,
        "scope": scope,
        "applicability": applicability,
        "candidateIdentity": candidate,
        "mutationIdentity": mutation,
        "completionIdentity": completion,
        "evidenceIdentities": evidence,
        "limitations": limitation_values,
        "status": "issued",
        "acceptanceState": "not-accepted",
    }

    receipt_id = _identity("receipt", material)

    if receipt_id is None:
        return _invalid(
            "non_canonical_receipt",
            "$",
            "Receipt material must be canonically serializable",
        )

    return ContractResult(
        "valid",
        {
            **material,
            "receiptId": receipt_id,
        },
        (),
    )


def evaluate_receipt_applicability(
    receipt: Mapping[str, Any],
    *,
    boundary: Mapping[str, Any],
    candidate_identity: str,
    configuration_identity: str,
    validator_identity: str,
) -> ContractResult:
    """Report applicability without changing the receipt."""
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("schema") != RECEIPT_SCHEMA
    ):
        return _invalid(
            "invalid_receipt",
            "$.receipt",
            "A Receipt is required",
        )

    criteria = {
        "boundaryId": (
            _text(boundary.get("boundaryId"))
            if isinstance(boundary, Mapping)
            else None
        ),
        "candidateIdentity": _identity_value(
            candidate_identity
        ),
        "configuration": _identity_value(
            configuration_identity
        ),
        "validator": _identity_value(
            validator_identity
        ),
    }

    applicability = receipt.get("applicability")

    if not isinstance(applicability, Mapping):
        return _invalid(
            "invalid_receipt_applicability",
            "$.receipt.applicability",
            "Receipt applicability must be a mapping",
        )

    actual = {
        "boundaryId": receipt.get("boundaryId"),
        "candidateIdentity": receipt.get(
            "candidateIdentity"
        ),
        "configuration": applicability.get(
            "configuration"
        ),
        "validator": applicability.get("validator"),
    }

    invalidators = [
        {
            "field": name,
            "expected": criteria[name],
            "actual": actual[name],
        }
        for name in sorted(criteria)
        if criteria[name] != actual[name]
    ]

    value = {
        "receiptId": receipt.get("receiptId"),
        "applicable": not invalidators,
        "invalidators": invalidators,
    }

    return ContractResult("valid", value, ())


def create_state_transition(
    *,
    prior_state: Mapping[str, Any],
    boundary: Mapping[str, Any],
    attached_receipt_ids: Sequence[str] = (),
    invalidated_receipt_ids: Sequence[str] = (),
    proposed_state: Mapping[str, Any],
) -> ContractResult:
    """Describe, but never accept, a state transition."""
    if not isinstance(prior_state, Mapping):
        return _invalid(
            "invalid_prior_state",
            "$.priorState",
            "Prior state and stateIdentity are required",
        )

    prior_state_identity = _identity_value(
        prior_state.get("stateIdentity")
    )

    if prior_state_identity is None:
        return _invalid(
            "invalid_prior_state",
            "$.priorState",
            "Prior state and stateIdentity are required",
        )

    if (
        not isinstance(boundary, Mapping)
        or boundary.get("schema") != BOUNDARY_SCHEMA
    ):
        return _invalid(
            "invalid_boundary",
            "$.boundary",
            "A valid BoundaryDescriptor is required",
        )

    boundary_id = _text(boundary.get("boundaryId"))

    if (
        boundary_id is None
        or not BOUNDARY_ID_PATTERN.fullmatch(boundary_id)
    ):
        return _invalid(
            "invalid_boundary",
            "$.boundary",
            "Boundary identity must match the "
            "BoundaryDescriptor contract",
        )

    attached = _identities(
        attached_receipt_ids,
        allow_empty=True,
        receipt_only=True,
    )
    invalidated = _identities(
        invalidated_receipt_ids,
        allow_empty=True,
        receipt_only=True,
    )

    if attached is None or invalidated is None:
        return _invalid(
            "invalid_receipt_ledger",
            "$",
            "Receipt ledgers must contain explicit, unique, "
            "canonical receipt identities",
        )

    if set(attached) & set(invalidated):
        return _invalid(
            "overlapping_receipt_ledger",
            "$",
            "A receipt cannot be attached and invalidated "
            "by one transition",
        )

    if not isinstance(proposed_state, Mapping):
        return _invalid(
            "invalid_proposed_state",
            "$.proposedState",
            "Proposed state must be an object",
        )

    prohibited = {
        "acceptanceState",
        "workflowAdvanced",
        "acceptedHistory",
    } & set(proposed_state)

    if prohibited:
        return _invalid(
            "acceptance_claim_in_proposal",
            "$.proposedState",
            "A proposal cannot claim acceptance or advancement",
        )

    normalized_prior_state = copy.deepcopy(prior_state)
    normalized_prior_state[
        "stateIdentity"
    ] = prior_state_identity

    material = {
        "schema": TRANSITION_SCHEMA,
        "normalizationVersion": NORMALIZATION_VERSION,
        "priorStateIdentity": prior_state_identity,
        "priorState": normalized_prior_state,
        "boundaryId": boundary_id,
        "attachedReceiptIds": attached,
        "invalidatedReceiptIds": invalidated,
        "proposedState": copy.deepcopy(proposed_state),
        "acceptanceState": "not-accepted",
        "workflowAdvanced": False,
    }

    transition_id = _identity(
        "state-transition",
        material,
    )

    if transition_id is None:
        return _invalid(
            "non_canonical_transition",
            "$",
            "Transition material must be canonically serializable",
        )

    return ContractResult(
        "valid",
        {
            **material,
            "transitionId": transition_id,
        },
        (),
    )
