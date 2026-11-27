# Collaboration Result contract

`collab/collaboration-result/v1` is the authoritative returned contract for exactly one bounded responsibility and exactly one Boundary Descriptor. A result is an untrusted producer claim. `completed` reports completion of the assigned responsibility only; it is not acceptance.

The contract keeps pre-continuation identities, reported observations, producer claims, later live verification, Result Acceptance, and accepted State Transition separate. Issue #70 defines only result production. Live applicability and Result Acceptance belong to Issue #71; atomic durable publication belongs to Issue #72.

The content-derived `resultId` is SHA-256 over canonical UTF-8 JSON of every normalized semantic field except `resultId` itself. Set-like fields and record collections are normalized deterministically. Paths are workspace-relative POSIX paths.

Outcomes are `completed`, `failed`, `blocked`, and `not-applicable`. Failed and blocked results may preserve partial artifacts, receipts, observations, and verification evidence. Blocked results identify the missing prerequisite or external condition. Not-applicable results identify the mismatch and cannot report completion.

Claims may reference declared candidates/artifacts and receipts/verification evidence. Internal references must resolve. Reported observations are not silently promoted to established evidence or accepted claims. Obligation claims retain their referenced obligation identities.

`requestedNextResponsibility` is advisory and declares its prerequisites. It does not authorize a successor. `documentationImpact` records affected normative paths. A Collaboration Result cannot contain self-acceptance or an accepted State Transition, and its pure implementation performs no observation or mutation.
