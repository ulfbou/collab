# Development Intent contract

## Definition

**Development Intent** is the normalized authorization for one bounded product
change. It connects hosted planning authority to durable documentation without
conflating them.

Issues authorize bounded product change. Documentation governs durable
semantics. Observations establish what a source reported. None silently
substitutes for another.

## Executable contract

The executable contract uses schema identity
`collab/development-intent/v1` and normalization version `1`.

Development Intent is derived from exactly one of:

1. a complete applicable hosted issue observation; or
2. explicit, accepted, issue-independent operational authorization.

These two derivations produce two distinct, closed schema variants
discriminated by `sourceKind`. Each variant declares its own closed property
set; a document that mixes fields from both variants, omits a variant-specific
required field, or carries an unsupported `sourceKind` value fails schema
validation. Structurally complete but semantically mixed documents are not
accepted.

The issue variant requires `source.repository`, `source.number`, and
`source.contentIdentity`, and requires `hostedState`. It cannot carry
operational-only fields. The operational variant requires `source.repository`,
`source.authorizationId`, and `source.contentIdentity`, plus `allowedMutation`,
`changedPathScope`, `exclusions`, `acceptanceConditions` (non-empty), and
`dependencies`. It cannot carry `hostedState`.

Issue-derived intent binds the repository, issue number, and a canonical
identity of the material issue content. The intent is not a second maintained
copy of the issue body. A material issue change therefore changes both the
issue content identity and the Development Intent identity.

Issue-independent authorization must be explicitly accepted and must identify
its repository, authorization, objective, expected boundary, mutation policy,
changed-path scope, exclusions, acceptance conditions, and dependencies.
Merely supplying operational prose does not establish accepted authorization.

Expected invalid input returns deterministic structured diagnostics. Derivation
is read-only and does not mutate issues, repositories, workspaces, or durable
workflow state.

Derivation reports failure in two layers. Input-layer failures return a
fail-closed result with no intent value. Content-layer failures specific to
AuthoritySet resolution are described below.

## AuthoritySet

An **AuthoritySet** is the versioned set of durable normative authorities
applicable to one Development Intent. Its executable schema identity is
`collab/authority-set/v1` and its normalization version is `1`.

AuthoritySet resolution preserves separately:

- declared authorities;
- resolved authority content and content identities;
- observed repository evidence;
- declaration-versus-observation conflicts;
- absent declarations;
- invalid declarations;
- incomplete evidence;
- resolution provenance;
- limitations.

Material declarations, authority-content identities, and provenance contribute
to `authoritySetId`. Equivalent normalized inputs are deterministic. A material
declaration, authority-content change, or declaration/observation provenance
change alters `authoritySetId`. Two resolutions that agree on declared
authorities, resolved authorities, and ledgers but differ in provenance are
distinct AuthoritySets.

Resolution reports failure in two layers. Input-layer failures return a
fail-closed result with no AuthoritySet. Content-layer failures return a
complete schema-conforming AuthoritySet whose `status` is `incomplete` or
`conflicted`, with structured diagnostics and role-specific ledgers
identifying the specific gap. `ResolutionResult.valid` is false whenever
`status` is not `resolved`, and no set can be `resolved` while any of
`invalidDeclarations`, `absentDeclarations`, `incompleteEvidence`, or
`conflicts` is non-empty. Every non-resolved result emits at least one flat
diagnostic in `ResolutionResult.diagnostics`; callers do not need to inspect
the ledgers to discover that resolution failed or why.

Each unambiguous resolved authority retains one primary owner:
`durable-documentation`. Conflicting claims remain explicit and are not
silently resolved by scoring or arbitrary precedence.

Authority path failures are classified rather than collapsed. An **unsafe
authority path** — absolute, containing `..` or `.` components, containing a
backslash or NUL byte, or otherwise violating the repository-relative
contract — is a declaration defect and is recorded in `invalidDeclarations`,
not `incompleteEvidence`. A structurally safe path that is **absent**, that
is **not a regular file** (directory, broken symlink, or symlink escaping the
repository root), or whose content is **unreadable** is recorded in
`incompleteEvidence` with distinct reasons
(`authority-content-missing`, `authority-content-not-file`,
`authority-content-unreadable`). Each of these categories emits at least one
flat diagnostic so the failure is explainable without inspecting the
ledgers.

An AuthoritySet identifies document kind, path, scope, read-only declaration,
declaration source, content identity, and provenance. It does not infer that
the documented behavior is implemented, current, validated, accepted, or
authorized for mutation.

## Repository-manifest contribution

A valid `collab/repository-manifest/v1` declaration contributes authority
candidates. The manifest remains a declaration rather than an observation.

- Manifest absence is recorded in `provenance`; it neither invents nor
  suppresses another authority and does not by itself produce `incomplete`.
  Required authorities that no declaration satisfies remain explicitly absent.
- Invalid, unavailable, or unrecognized manifests cannot contribute resolved
  authorities, are recorded in `invalidDeclarations` with distinct reasons,
  and emit a flat `manifest_invalid`, `manifest_unavailable`, or
  `unknown_manifest_status` diagnostic.
- A missing declared document produces incomplete evidence.
- A difference between observed and repository content identities remains an
  explicit conflict.
- Manifest declarations never prove implementation, current state, validation,
  acceptance, or mutation authority.

## Authority boundaries

- **Collab** owns Development Intent interpretation, AuthoritySet resolution,
  applicability, acceptance semantics, continuation meaning, and Current State.
- **Gitdrift** owns read-only repository-state, alignment, semantic-regression,
  obligation, and provenance findings.
- **DX Artifacts** owns DX format semantics, carrier determinism, conformance,
  and release behavior.
- **DXS/Dx.Cli** owns transactional workspace mutation, snapshots, sessions, and
  differential execution.
- **Repository-owned validators** own repository-specific executable gates.
- **Human acceptance** owns reserved approvals and consequential decisions.

Resolution does not transfer ownership among these authorities.

## Required separation

Development Intent remains distinct from:

- a hosted issue description;
- a branch name;
- a repository manifest;
- an observation;
- an obligation;
- a mutation plan;
- a user approval.

Observed evidence, issue intent, and documentation authority remain distinct.
Cached or stale observations do not determine mutation authority.

## Applicability

A changed issue identity or AuthoritySet identity changes applicability.
Dependent prepared work must be re-evaluated rather than silently retaining the
old applicability identity.

Continuation cannot edit Development Intent or replace its AuthoritySet merely
to make a result acceptable.

## Explicit Issue #63 exclusions

This contract does not implement:

- obligation normalization;
- Boundary, Receipt, or Transition contracts;
- boundary execution;
- continuation classification;
- partial-attempt records;
- generic collaboration results;
- result acceptance;
- accepted-transition publication;
- repository or hosted mutation.

Obligation normalization remains owned by Issue #64.
