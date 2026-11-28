# Result Acceptance contract

Result production, Result Acceptance, and durable transition publication are separate responsibilities. A `CollaborationResult` is untrusted producer output. Issue #71 normalizes it through the canonical Issue #70 implementation, verifies it, and returns a deterministic decision. Only Issue #72 may construct or publish durable state.

## Inputs and trust boundary

Acceptance consumes the result, controlling material state and boundary identities, authorized paths, required artifacts and receipts, and explicitly supplied live evidence. Producer claims and reported observations remain distinct from acceptance-owned conclusions. Receipt existence, branch names, issue numbers, filenames, local state, and producer observations never establish applicability by themselves.

## Verification layers

1. **Structural:** canonical `normalize_collaboration_result` verifies versions, result identity, references, unique IDs, responsibility/outcome rules, self-acceptance, durable-transition prohibition, and read-only mutation reporting. Failure stops later applicability evaluation.
2. **Applicability:** material state, boundary, responsibility, intent, authority, obligations, candidate, baseline, configuration, policy, validator, and repository-manifest identities are compared independently. A changed capture identity alone is harmless when material identities remain unchanged.
3. **Scope:** normalized changed paths must be authorized. Read-only boundaries reject reported mutation. Missing changed-path evidence remains missing evidence.
4. **Artifacts and receipts:** required declarations must be present and match their immutable identities. Receipts must cover the current operation and controlling identities. Byte-valid but stale evidence is not reusable; unrelated completed evidence is retained.
5. **Live evidence:** missing live evidence and failed live verification are distinct. Live inputs may establish local, hosted, candidate, baseline, authority, validator, artifact, receipt, and negative-effect facts without granting mutation authority.

Stable diagnostics distinguish stale state, boundary and responsibility mismatch, changed intent/authority/obligations/candidate/baseline/configuration/policy/validator/repository manifest, inapplicable receipts, artifact mismatch, scope excess, missing live evidence, and failed live verification.

## Outcomes and negative guarantees

`ACCEPTED` is transition-eligible, but it does not contain, persist, or publish a transition. Partial, blocked, and failed outcomes retain applicable claims, observations, artifacts, receipts, and completed independent work while leaving the boundary incomplete. Stale results are rejected, structural failures require candidate repair, missing live evidence requires re-observation, and remaining obligations stay explicit. No merge, synchronization, cleanup, candidate edit, hosted mutation, receipt mutation, or durable-state mutation is inferred or performed.

## Determinism

The decision uses canonical UTF-8 JSON, sorted object keys, deterministic set-like ordering, and the repository's `sha256:<kind>:v1:<digest>` convention. Reordering set-like inputs does not change the decision identity; semantic changes do. A supplied decision identity must match. Unknown schema properties are rejected.

## Independent artifact integrity evidence

A producer artifact record is untrusted. Its `identity` is the declared immutable content or backing identity; its canonical JSON `details` carries the declared lowercase SHA-256 and non-negative byte size. Acceptance requires a separate `artifactIntegrityEvidence` record from an identified independent verifier. The evidence must name the artifact, immutable identity, SHA-256, byte size, collaboration-result identity, operation, boundary, candidate, verifier, and whether bytes were rehashed or an immutable backing was attested. Merely copying producer declarations is malformed evidence. Issue #71 compares supplied declarations, independent evidence, and controlling identities. It does not fetch artifacts or claim to hash bytes itself.

## Independent receipt integrity and applicability

Receipt integrity and applicability are separate gates. A required receipt needs independently supplied evidence for its immutable identity, canonical receipt-content SHA-256, non-negative byte size, issuer, verifier, operation, boundary, material state, candidate, baseline, authority, obligation, configuration, policy, validator, and repository manifest. Byte-valid evidence remains inapplicable if any controlling identity differs. Issue #71 neither creates nor mutates receipts and does not redesign the receipt contract.

## Outcome and schema agreement

The implementation and schema share the complete outcome vocabulary: `ACCEPTED`, `PARTIAL_EVIDENCE_RETAINED`, `BLOCKED_EVIDENCE_RETAINED`, `FAILED_EVIDENCE_RETAINED`, `STALE_REJECTED`, `STRUCTURALLY_INVALID`, `REQUIRES_LIVE_REOBSERVATION`, and `REQUIRES_CANDIDATE_REPAIR`. Only `ACCEPTED` is transition eligible and it requires every verification gate to pass, no diagnostics, and `PUBLISH_TRANSITION`. That continuation is permission for the separately owned Issue #72 publication operation, not publication by Issue #71. Every non-accepted outcome is ineligible and cannot request publication.
