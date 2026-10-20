# Controlled evidence-bound collaboration roadmap

## Status and authority

This document is the authoritative planning interpretation for Collab's
boundary-centric collaboration program. It controls roadmap meaning but does
not replace hosted issue state, repository evidence, executable validation,
receipts, or human acceptance.

The machine-readable representation is
../../roadmap/evidence-bound-collaboration.json
and uses schema identity `collab/controlled-roadmap/v1`.

## Authority boundaries

- **Collab** owns collaboration meaning, Current State, applicability,
  continuation, result acceptance, and the controlled roadmap.
- **Gitdrift** owns read-only semantic repository-state, alignment, regression,
  obligation, provenance analysis, and its proposed external repository
  harness.
- **DX Artifacts** owns DX format semantics, deterministic carriers,
  conformance, and releases.
- **DXS/Dx.Cli** owns transactional workspace mutation, snapshots, sessions,
  and differential execution.
- **Repository-owned validators** own repository-specific executable gates.
- **Human acceptance** remains the authority for reserved approval,
  publication, and consequential decisions.

No authority silently substitutes for another.

## Planning states

`PROPOSED`, `ACCEPTED`, `READY`, `ACTIVE`, `REVIEW`, `BLOCKED`,
`DEFERRED`, `COMPLETED`, `SUPERSEDED`, and `REJECTED` describe controlled
planning interpretation. They do not overwrite hosted issue or pull-request
state.

## Completed foundations

The roadmap preserves these completed foundations and integration provenance:

1. Issue #60 / PR #83: boundary-centric collaboration.
2. Issue #61 / PR #84: Current State Record identity.
3. Issue #62 / PR #86: local and hosted observation contracts.
4. Issue #85 / PR #87: repository manifest declaration contract.

Their progression is `#60 → #61 → #62 → #85 → #63`. A later defect requires
a new bounded correction. PR #84's historical branch name is provenance only.

## Core implementation horizons

### A. Semantic foundation

`#63 → #64 → #65`

Issue #63 depends on Issues #61, #62, and #85. This horizon establishes
Development Intent, AuthoritySet resolution, normalized obligations, Boundary,
Receipt, and Transition contracts. It performs no repository or hosted
mutation.

### B. Preparation and continuation

`#66 → #67` and `#68 → #69`

Evidence selection, artifact materialization, continuation classification, and
partial-attempt recording remain distinct responsibilities.

### C. Results, acceptance, and publication

`#70 → #71 → #72`

A process result remains an untrusted claim until applicability and live
verification pass. Acceptance alone authorizes a durable transition.

### D. Read-only reconvergence

Issue #73 is the mandatory executable read-only vertical slice before any
mutation-capable work.

### E. DX and compatibility

`#74 → #75`

The checked-in `dx.py` remains Collab's sole production DX implementation.
New or changed carriers use the current DX v2 production format and the
`.dx.txt` extension. Lead and Senior remain compatibility profiles until their
bounded adaptation.

### F. Mutation boundaries

`#76 → #77 → #78 → #79 → #80 → #81`

All mutation-capable work depends on Issue #73. Integration, synchronization,
and cleanup remain separately represented and ordered. Cleanup cannot precede
successful synchronization.

### G. Orchestration demotion

Issue #82 demotes broad scripts into adapters, profiles, bounded compositions,
or compatibility wrappers over established library semantics.

## Proposed evidence-bound workflow library

The proposed workflow-library specification maps onto Issues #63–#82. It is
not implemented state and is not a second backlog. The library remains inside
Collab initially.

Extraction is permitted only after demonstrated use by:

1. Collab;
2. the Gitdrift external repository harness; and
3. one meaningfully independent consumer.

## Gitdrift external repository testing

The proposed Gitdrift specification remains owned by `ulfbou/gitdrift`.
Specification review follows stabilization of Issue #65. Harness
implementation requires separately accepted specification evidence and a
completed Issue #73 gate.

Its first implementation slice remains one repository, one immutable revision,
one acquisition mode, one disposable workspace mode, one installed Gitdrift
candidate, one request type, one assertion family, one mutation sentinel, and
one external receipt. The pinned `dx-artifacts` corpus is the preferred
reference until newer accepted evidence establishes another start.

## Separate GitHub caching program

Epic #39 and Issues #42–#47 remain a separate infrastructure program outside
the critical path. Caching may optimize hosted observation but cannot determine
authority, Current State, receipt applicability, accepted transitions, or the
need for live reobservation before mutation.

## Related unresolved work

- Issue #16 supplies read-only reconvergence and end-to-end validation input
  to Issue #73.
- Issue #17 remains architecture provenance and a proof-of-concept outcome
  record.
- Issue #18 remains Windows DX recovery and regression evidence related to
  Issue #74.

Architectural similarity alone does not close or supersede these issues.

## Controlled gates

The machine-readable roadmap enforces:

- unique identities and primary capability ownership;
- resolvable and acyclic dependencies;
- preserved completed foundations;
- proposal-versus-implementation separation;
- Issue #63 dependency on Issues #61, #62, and #85;
- ordered Issues #64–#82;
- Issue #73 before mutation;
- accepted-specification and Issue #73 gates for the external harness;
- integration before synchronization before cleanup;
- independent adoption before extraction; and
- mechanical derivation of Issue #63 as the next implementation item.

## Non-goals

This roadmap does not implement Issue #63, runtime behavior, caching, the
Gitdrift harness, DX codec changes, compatibility adaptation, mutation,
publication, review, integration, synchronization, cleanup, automatic issue
closure, or a standalone library. It never substitutes roadmap claims for live
repository or hosted evidence.
