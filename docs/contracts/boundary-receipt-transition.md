# Boundary, receipt, and transition contracts

Issue #65 establishes three identity-bound, read-only semantic contracts. They describe pending responsibility, completion evidence, and a proposed state transition. They do not execute work or accept results.

## BoundaryDescriptor

A BoundaryDescriptor owns exactly one legitimate responsibility. It binds that responsibility and its scope to controlling baseline, configuration, validator, Current State, Development Intent, AuthoritySet, ObligationSet, and subject identities. Its deterministic `boundaryId` covers every material field. A boundary remains `pending`; construction does not execute it.

## Receipt

A Receipt is immutable evidence that work declared completion against one boundary. Its deterministic `receiptId` binds scope, candidate, baseline, configuration, validator, state, intent, authority, obligation, subject, mutation, completion, evidence, and limitations. `acceptanceState` remains `not-accepted`. Applicability evaluation compares identities and returns explicit invalidators without changing the receipt. Receipt invalidation is recorded by a later StateTransition, never by mutating the issued Receipt. A receipt is neither implementation proof outside its applicability nor authorization to advance state.

## StateTransition

A StateTransition preserves the complete prior state and its semantic identity. It records a proposed state plus duplicate-free, disjoint ledgers of canonical receipt identities. A proposed state cannot claim acceptance, workflow advancement, or accepted history. All identity-bearing input is normalized before inclusion, and non-serializable material fails closed. Its deterministic `transitionId` covers the complete proposal. `workflowAdvanced` is always false and `acceptanceState` is always `not-accepted`; only a later Result Acceptance boundary may authorize durable advancement.

## Exclusions and preservation

These contracts perform no operation, validator execution, acceptance decision, repository or workspace mutation, Git operation, network access, subprocess execution, hosted-state mutation, integration, synchronization, cleanup, or workflow advancement. Current State observations remain evidence, Development Intent remains change authorization, AuthoritySet remains durable authority resolution, and ObligationSet remains the normalized requirement boundary. No declaration or receipt is promoted beyond its explicit role.
