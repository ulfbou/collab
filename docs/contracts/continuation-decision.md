# Continuation Decision contract

`collab/continuation-decision/v1` is the closed, read-only result contract for classifier version 1. It selects the smallest valid continuation for exactly one pending Issue #65 Boundary and never changes its `boundaryId`.

## Predecessor evidence and receipt reuse

The classifier accepts the established `collab/boundary-descriptor/v1` Boundary and optional `collab/receipt/v1` Receipt unchanged. It delegates applicability to `collab.boundary_contracts.evaluate_receipt_applicability()`. Reuse therefore requires the Issue #65 boundary ID plus candidate, configuration, and validator identities to remain applicable. The boundary ID already binds baseline and the other material predecessor identities. The classifier neither defines a parallel receipt nor mutates the Boundary, Receipt, or applicability result.

## Decisions and inconsistency

The complete set is `EXECUTE_BOUNDARY`, `REUSE_RECEIPT`, `RESUME_PARTIAL_BOUNDARY`, `REPAIR_NARROW_FAILURE`, `WAIT_FOR_HOSTED_STATE`, `REOBSERVE_STATE`, `REQUEST_EVIDENCE`, `REQUEST_DECISION`, and `REJECT_INCONSISTENT_STATE`.

Ordinary conflicting authority, hosted, or observed evidence is recoverable and yields `REOBSERVE_STATE`; it does not imply restart or discarded work. Rejection requires the explicit `inconsistencyState` value `IRRECONCILABLE`. Reserved human authority yields `REQUEST_DECISION`, incomplete hosted evidence yields `WAIT_FOR_HOSTED_STATE`, and missing evidence reports only exact normalized domains. Partial and narrow-failure decisions classify only; no attempt ledger or repair execution exists.

## Blocked operations and purity

`blockedOperations` reports only blockers established by supplied state and is sorted deterministically. `EXECUTE_BOUNDARY` therefore reports no execution blocker unless one is supplied as evidence. Separately, the classifier implementation is pure: it performs no file access, path or symlink traversal, repository write, Git or subprocess operation, network call, hosted mutation, execution, acceptance, integration, synchronization, or cleanup.

## Determinism and exclusions

Canonical JSON serialization covers the complete Boundary, Receipt, applicability inputs, states, and set-like evidence in `classifierIdentity`. Equivalent normalized input has one identity; any material change has another. Unsupported properties, duplicate set-like values, malformed predecessor evidence, and noncanonical identity-bearing data fail closed.

A decision is not execution or acceptance. This contract does not implement retry policy, attempt recording, workflow advancement, boundary replacement, integration, synchronization, cleanup, Issue #69 capability, or any change to Development Intent, AuthoritySet, obligations, predecessor schemas, or predecessor identities.
