# ObligationSet contract

Issue #64 establishes the read-only boundary `Development Intent + AuthoritySet + identity-bound source material -> ObligationSet`.

Callers provide bounded source material, not pre-normalized obligations or pre-solved conflicts. Every source item binds one provenance reference to requirements identified by `sourceRequirementId`. Issue or accepted operational authorization content must be represented by Development Intent; durable content must be represented by `AuthoritySet.resolvedAuthorities`. Observed repository evidence is never promoted to authority.

Every complete applicable requirement becomes a deterministic obligation with source, statement, affected scope, required evidence, a declarative non-mutating verification contract, `unverified` completion state, and limitations. Missing fields or unavailable/non-authoritative content become explicit incomplete obligations without invented values. Upstream AuthoritySet conflicts remain unresolved, with no inferred precedence. Therefore each supplied requirement appears exactly once as an obligation or incomplete obligation, while upstream conflicts remain separately explicit.

Identity covers all material content. Set-like arrays and output order are canonical. Ordering changes do not alter identities; source-content, statement, scope, evidence, verification, and limitation changes do.

Status is `normalized` only with resolved authority, no incompleteness, and no conflict. Schema-invalid combinations are rejected. Normalization executes no validator, subprocess, network, Git, mutation, receipt, acceptance decision, integration, synchronization, cleanup, or workflow transition. `verificationExecuted` is always false and `acceptanceDecision` is always `not-performed`.

The authoritative import path is `collab.obligation_normalization`. Issue #64 does not expand the package-root API.
