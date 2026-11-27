# Result Acceptance contract

Result production and Result Acceptance are separate responsibilities. The normative returned structure is defined in [Collaboration Result](collaboration-result.md). Every Collaboration Result, including a `completed` result, remains untrusted until the Issue #71 acceptance responsibility performs structural, applicability, scope, receipt, and required live verification.

Acceptance must distinguish evidence established before continuation, observations reported by the continuation, claims derived by the continuation, live verification, the acceptance decision, and any later accepted State Transition. A failed, blocked, or partial result may still preserve truthful evidence without completing the boundary.

Acceptance does not itself permit a producer to advance durable state. Atomic publication of an accepted transition belongs to Issue #72.
