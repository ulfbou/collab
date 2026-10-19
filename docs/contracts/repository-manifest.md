# Repository manifest declaration contract

## Contract identity and location

A repository manifest is a human-governed declaration with schema identity
`collab/repository-manifest/v1`. Consumers read it from
`.repository/manifest.json`. The manifest schema version is independent of the
Collab product, Current State Record, consumer-product, and DX carrier versions.
The canonical structural schema is `schemas/repository-manifest.schema.json`
and uses JSON Schema Draft 2020-12.

## Authority boundary

The manifest declares durable repository intent. It does not observe current
Git or hosted state, report execution or validation success, record acceptance,
advance workflow state, or infer repository purpose. Consumers keep four kinds
of information separate:

1. declared repository intent from this manifest;
2. observed local or hosted evidence;
3. derived alignment findings with provenance to declaration and observation;
4. accepted workflow state established only by result acceptance.

A declaration may be compared with observations but never silently replaces
them. Loading and validation are read-only and never execute declared entry
points.

## Core model

The closed core object declares:

- canonical `owner/name` repository identity;
- product identity, name, purpose, and optional audiences;
- lifecycle: `experimental`, `active`, `maintenance`, `deprecated`, or `historical`;
- canonical workspace and engineering entry points;
- intentional components and component dependencies;
- durable policy, contract, schema, decision, and documentation authorities;
- release units and independent version domains;
- public, internal, generated, historical, and read-only boundaries;
- repository relationships;
- durable invariants and non-goals;
- collection include/exclude policy and alignment-authority references;
- controlled, namespaced extensions.

Empty arrays are explicit empty declarations, not absence. Extension keys use
`namespace/name`; extension values are owned by that namespace and do not add
core semantics.

## Paths and references

All paths are repository-relative, non-empty, `/`-separated paths. Absolute,
drive-qualified, backslash-separated, NUL-containing, empty-segment, `.` and
`..` paths are invalid. Every core repository-path declaration must resolve
beneath the explicit repository root supplied to validation, including workspace
and engineering entry points, component paths, authority paths and scopes,
release artifacts, version-domain source paths, boundary paths, and collection
include/exclude paths.

Identifiers are stable within their collection. Component dependencies and
release-unit component references resolve to components. Release-unit version
references resolve to version domains. Alignment authority references resolve
to authorities. A path cannot simultaneously belong to two core boundary
classes because those declarations are contradictory.

## Result states and diagnostics

The loader returns:

- `not_declared` when the conventional file is absent;
- `valid` for a structurally and semantically valid declaration, including an
  explicitly empty valid declaration;
- `invalid` for unreadable JSON, structural violations, unsupported schema
  identity, unresolved references, missing required repository paths, duplicate
  identifiers, or contradictory boundaries;
- `unavailable` when the supplied repository root or declaration evidence
  cannot be read.

Diagnostics have stable `code`, manifest `path`, and bounded `message` fields,
ordered deterministically. Invalid declarations do not prevent unrelated
repository observation and do not become authority candidates.

## Prohibited persistent state

The manifest cannot declare current branch, commit, worktree, issue, pull
request, milestone, check, review, environment, build result, test result,
package result, deployment result, validation receipt, or acceptance result.
Such facts belong to observations or immutable receipts, not durable declared
intent.

## Conformance

`tests/fixtures/repository-manifest/minimal-valid.json` demonstrates the minimum
closed declaration. `complete-valid.json` exercises every core area.
`gitdrift-valid.json` demonstrates product-specific evidence only through a
namespaced extension. Invalid fixtures cover structural failure, paths,
duplicate identifiers, unresolved references, unsupported identity,
contradictory boundaries, and unresolved authority paths.
