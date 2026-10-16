# Boundary-centric collaboration model

## Status and scope

This document establishes the controlling architecture for evidence-grounded,
issue-directed collaboration. It defines the durable semantics consumed by
later implementation increments. It does not implement the future workflow.

Collab already implements a substrate for repository discovery, GitHub reads
and bounded mutations, validated profiles, diagnostics, atomic filesystem
writes and recovery, evidence collection and equivalence, immutable run
records, stable artifact publication, delivery recovery, dry-run non-mutation,
validation, and DX carrier processing. Those capabilities remain governed by
their existing contracts.

## Authority model

Collaboration uses distinct authorities. No authority silently substitutes for
another.

1. **Observed evidence** is a source-attributed account of what a source
   reported at capture time. Evidence establishes observed state. It does not
   authorize product change or define durable semantics.
2. **Development Intent** is the normalized, issue-directed authorization for
   one bounded product change. The issue directs the objective, scope,
   exclusions, acceptance conditions, and planning relationships.
3. **Normative documentation** governs durable product semantics. The
   applicable documents form the Development Intent's **Authority Set**.
4. A **normalized obligation** is a uniquely identified, testable statement
   derived from Development Intent or its Authority Set without weakening,
   strengthening, discarding, or inventing authority.
5. A **Current State Record** relates observations, relationships,
   classifications, verification, accepted history, completeness, consistency,
   and limitations for one captured collaboration state.
6. A **Boundary Descriptor** identifies exactly one pending transactional
   boundary and binds that boundary to the identities and obligations that make
   it applicable.
7. A **Receipt** is an immutable, applicability-bound record of a bounded
   operation and its identified inputs and outputs.
8. A **Collaboration Result** is the generic result returned by bounded
   continuation. It reports outcome and evidence but cannot advance durable
   workflow state.
9. **Result Acceptance** evaluates a Collaboration Result against current
   state, intent, authority, obligations, and receipts.
10. An **accepted State Transition** is the durable transition created only by
    successful Result Acceptance.

Issue authority and documentation authority remain distinct:

- evidence establishes observed state;
- issues authorize bounded product change;
- documentation governs durable semantics;
- executable validation verifies identified obligations;
- receipts record applicable operations;
- acceptance alone advances durable workflow state.

The detailed contracts are:

- [Current State contract](../contracts/current-state.md)
- [Development Intent contract](../contracts/development-intent.md)
- [Boundary contract](../contracts/boundaries.md)
- [Receipt contract](../contracts/receipts.md)
- [Result Acceptance contract](../contracts/result-acceptance.md)

## Target lifecycle

The controlling lifecycle is:

```text
observed evidence
  + issue-directed Development Intent
  + normative Authority Set
  -> normalized obligations
  -> Current State Record
  -> one identity-bound pending Boundary Descriptor
  -> bounded preparation
  -> bounded continuation
  -> Collaboration Result and immutable receipts
  -> Result Acceptance
  -> accepted State Transition
  -> subsequent Current State Record
```

Preparation may establish sufficient context and describe one pending boundary.
Preparation cannot complete the development boundary.

Continuation may perform exactly the pending boundary. It cannot select another
issue, redefine scope, replace authorities, weaken obligations, or silently
substitute another boundary.

Acceptance alone advances durable workflow state.

## Responsibility boundaries

- **Preparation** constructs a bounded context projection and identifies one
  pending boundary.
- **Continuation** performs exactly that pending boundary and returns a
  Collaboration Result with receipts.
- **Acceptance** determines applicability and satisfaction and may create an
  accepted State Transition.
- **Integration** combines an accepted candidate with a target history.
- **Synchronization** updates another repository or workspace view to an
  already integrated state.
- **Cleanup** removes temporary branches, files, leases, or projections when
  their retention obligations permit removal.

Integration, synchronization, and cleanup are separate responsibilities.
Success in one does not prove completion of another. Cleanup must not remove
immutable run evidence, recovery material, or evidence required by an accepted
transition.

## Bounded context projection

Full repository context is not the default.

A **bounded context projection** is the smallest set of evidence, authorities,
obligations, prior receipts, identities, and limitations sufficient for one
pending boundary. Projection preserves provenance and explicit completeness.
Omitted material is recorded as unavailable, excluded, or not applicable. It is
not silently treated as absent.

Preparation, continuation, and acceptance consume the same semantic contracts
and applicability identities even when their human-facing presentations
differ.

## Compatibility policy

Lead and Senior profiles remain supported compatibility presentations during
migration. They may shape generated instructions or display, but they are not
workflow-state authorities and do not determine the pending boundary.

Existing Lead and Senior behavior remains available until a later bounded issue
migrates its consumer. This architecture does not delete either profile or
rewrite the existing delivery workflow.

`repository-state.json` remains a compatibility representation. It is not
retroactively treated as the complete Current State Record. Current State
identity and migration belong to later implementation increments.

The checked-in `dx.py` is the production carrier authority for DX parsing,
inspection, verification, packing, unpacking, and application. DX v2 production
behavior and intentionally retained historical DX compatibility remain
unchanged. No independent carrier interpretation becomes a second production
authority.

## Migration completion

The boundary-centric migration is complete only when later accepted increments
establish all of the following:

1. Current State capture and identity are implemented and validated.
2. Development Intent and Authority Set resolution are executable.
3. One identity-bound pending Boundary Descriptor is produced without
   automatic issue selection.
4. Preparation produces bounded context without completing development work.
5. Continuation accepts and preserves the pending boundary without redefining
   it.
6. Receipts are immutable and applicability-bound.
7. Collaboration Results are generic across boundary kinds.
8. Result Acceptance is the sole durable transition authority.
9. Integration, synchronization, and cleanup remain separately represented.
10. Lead, Senior, and `repository-state.json` compatibility is either retained
    or migrated through explicitly accepted boundaries.
11. Documentation, schemas, implementation, tests, diagnostics, and hosted
    workflow evidence agree.

Each hosted child issue owns one bounded implementation pull request. The
hosted issue set is the authoritative decomposition. This document does not
renumber or silently reinterpret it.

## Major exclusions

This architecture does not:

- add a preparation command;
- migrate Current State;
- delete Lead or Senior profiles;
- rewrite delivery;
- select issues automatically;
- generate a new carrier;
- implement schemas or Python behavior owned by later issues;
- restructure unrelated documentation.

## Existing, controlling, compatibility, and later behavior

- **Existing implemented substrate:** immutable runs, stable artifact
  publication, atomic writes and recovery, profile security and validation,
  evidence equivalence, repository discovery, GitHub read and mutation
  boundaries, dry-run non-mutation, delivery recovery, diagnostics,
  repository contracts, DX v2 behavior, and retained historical DX
  compatibility.
- **Controlling architecture established here:** authority separation,
  vocabulary, Current State structure, identity model, boundary model, receipt
  applicability, preparation and continuation constraints, acceptance
  authority, responsibility separation, compatibility policy, production DX
  authority, bounded context projection, and migration completion criteria.
- **Compatibility behavior retained during migration:** Lead and Senior
  presentation, `repository-state.json`, and present delivery workflows.
- **Later implementation obligations:** child issues under the milestone
  implement schemas, identity, capture, preparation, continuation, acceptance,
  migrations, commands, and workflow changes. Those roadmap obligations are
  not implemented behavior.
