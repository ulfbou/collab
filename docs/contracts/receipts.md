# Receipt contract

## Definition

A **Receipt** is an immutable, applicability-bound record that a bounded
operation was attempted or completed against identified inputs.

A receipt is evidence. It is not acceptance and is not mutable workflow state.

## Required identity

A receipt records:

- receipt schema and producer identity;
- operation and Boundary Descriptor identity;
- Current State stateIdentity and applicable captureId;
- Development Intent and Authority Set identities;
- normalized obligation identities;
- repository, hosted, artifact, configuration, and validator identities;
- start and finish observations;
- outcome and diagnostics;
- output identities;
- completeness and limitations;
- canonical or cryptographic identity where its contract provides one.

A receipt applies only when its declared identity dimensions satisfy the
consumer's applicability requirements. Similar prose, the same issue number,
or the same boundary enum is insufficient.

## Immutability and correction

Receipts are append-only. Correction creates a new receipt linked to the
superseded attempt.

Existing immutable run records and artifact identities remain authoritative
evidence under their established contracts. They are not rewritten into the
new model.

## Reuse

A consumer may reuse a receipt only when all declared applicability dimensions
remain unchanged, including candidate, baseline, configuration, authority,
obligation set, validator, and policy identity.

Reuse is an explicit acceptance decision. Continuation cannot assume it.

Stable published artifacts remain operator-facing references. Their immutable
run-backed identities remain the evidence authority described by
../delivery-artifacts.md.
