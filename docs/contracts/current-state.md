# Current State contract

## Definition

A **Current State Record** is the immutable semantic account of one captured
collaboration state. It is the common state contract consumed by preparation,
continuation, and Result Acceptance.

A Current State Record does not replace source evidence, authorize product
change, or advance durable workflow state merely because it was captured.

## Required separation

A Current State Record keeps these sections distinct:

1. **Observations:** source-attributed facts captured without classification.
2. **Relationships:** explicit links among repository, hosted, filesystem,
   artifact, run, issue, pull-request, authority, and prior-state identities.
3. **Classifications:** derived interpretations such as aligned, pending,
   accepted, incomplete, stale, or contradictory.
4. **Verification:** checks performed, identified inputs, validator identity,
   results, and evidence references.
5. **Accepted history:** accepted State Transitions and the prior identities
   they extend or supersede.
6. **Completeness:** what was requested, obtained, omitted, unavailable, or not
   applicable.
7. **Consistency:** known agreement or conflict among observations,
   authorities, obligations, receipts, and accepted history.
8. **Limitations:** uncertainty, staleness, inaccessible sources, bounded
   projections, and unsupported claims.

Observed evidence remains separate from derived classification. Every
classification identifies the evidence and rule from which it was derived.

## Identity

**captureId** identifies one capture event or one materialized Current State
Record. A repeated capture has a distinct captureId even when it observes an
equivalent semantic state.

**stateIdentity** identifies the normalized semantic state represented by a
Current State Record. Equivalent normalized states may share a stateIdentity
across different captures.

Neither identity substitutes for source identities such as commit SHA, branch
tip, artifact hash, run ID, issue number, pull-request head, configuration
identity, or request identity.

The stateIdentity normalization contract is versioned and included in
applicability evaluation.

## Invariants

- A published Current State Record is append-only.
- Every observation names its source and capture status.
- Every classification retains derivation provenance.
- Completeness, consistency, and limitations are explicit.
- Accepted history contains only transitions created by Result Acceptance.
- A pending Boundary Descriptor references stateIdentity and references
  captureId whenever capture freshness applies.
- A new capture does not by itself advance durable workflow state.
- `repository-state.json` remains a compatibility representation until a later
  accepted migration explicitly adapts or replaces it.
