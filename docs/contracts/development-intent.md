# Development Intent contract

## Definition

**Development Intent** is the normalized, issue-directed authorization for one
bounded product change.

It connects hosted planning authority to durable documentation without
conflating them. Issues authorize bounded product change. Documentation governs
durable semantics.

## Authority Set

An **Authority Set** is the versioned set of normative documents applicable to
one Development Intent.

It identifies:

- document and version identities;
- applicable sections;
- precedence rules;
- supersession relationships;
- known conflicts;
- unresolved limitations.

An issue does not become normative documentation merely because it requests a
change. Documentation does not select an issue or prove observed repository or
hosted state.

## Required content

Development Intent contains:

- repository and issue identity;
- objective and expected boundary;
- allowed mutation and changed-path scope;
- explicit exclusions and non-goals;
- acceptance conditions;
- dependencies and issue relationships;
- observed hosted labels, milestone, and state;
- Authority Set;
- normalized obligations;
- unresolved authority conflicts and limitations.

## Normalized obligations

A **normalized obligation** is a uniquely identified, testable statement
derived from Development Intent or its Authority Set.

Each obligation records:

- source and provenance;
- applicability;
- required, prohibited, or informational strength;
- verification method;
- satisfaction evidence;
- unresolved conflict or limitation.

Normalization may remove wording variation. It may not weaken, strengthen,
invent, or silently discard authority.

## Rules

- Evidence establishes observed state.
- Issues authorize bounded product change.
- Documentation governs durable semantics.
- Issue authority and documentation authority remain distinct.
- Conflicts are explicit and block only dependent operations.
- Automatic issue selection is outside this architecture.
- Continuation cannot edit Development Intent to make its result acceptable.
- A changed issue or Authority Set changes applicability and requires the
  pending boundary to be prepared or accepted against the new identity.
