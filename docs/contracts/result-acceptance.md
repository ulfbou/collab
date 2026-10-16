# Result acceptance contract

## Collaboration Result

A **Collaboration Result** is the generic return from bounded continuation.

It contains:

- Boundary Descriptor identity;
- outcome: completed, failed, blocked, or not applicable;
- produced candidate and artifact identities;
- changed-path and mutation evidence;
- verification receipts and diagnostics;
- obligation-by-obligation claims;
- completeness, consistency, and limitations;
- requested next responsibility.

A Collaboration Result does not advance durable workflow state and cannot
declare itself accepted.

## Result Acceptance

**Result Acceptance** is the sole authority that advances durable collaboration
state.

Acceptance verifies:

1. the result applies to the pending Boundary Descriptor and Current State
   identity;
2. Development Intent and Authority Set identities remain applicable;
3. required normalized obligations are satisfied;
4. prohibited behavior did not occur;
5. observed evidence remains distinct from derived claims;
6. changed paths and mutations remain within scope;
7. required validation and receipts are complete and identity-bound;
8. no established obligation is weakened;
9. immutable runs, stable artifacts, atomic publication, recovery, and
   compatibility contracts remain consistent;
10. limitations are acceptable for the boundary.

Successful acceptance returns an immutable acceptance receipt. Rejection,
failure, or non-applicability records diagnostics but does not create an
accepted State Transition.

## Accepted State Transition

An **accepted State Transition** links:

- prior stateIdentity;
- accepted Boundary Descriptor identity;
- accepted Collaboration Result identity;
- acceptance receipt identity;
- satisfied normalized obligation identities;
- resulting stateIdentity or the rule for capturing it;
- successor responsibility, when applicable.

Only an accepted State Transition enters accepted history.

Preparation, continuation, validation success, commit, push, pull-request
creation, integration, synchronization, and cleanup may provide evidence. None
independently advances durable workflow state.

Integration, synchronization, and cleanup are accepted separately when each is
represented by its own pending Boundary Descriptor. A later Current State
Record observes their effects and incorporates only accepted transitions into
durable history.
