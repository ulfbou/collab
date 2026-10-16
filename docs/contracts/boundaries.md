# Boundary contract

## Definition

A **Boundary Descriptor** is the immutable, identity-bound description of
exactly one pending transactional boundary.

A boundary is not merely an enum value such as `IMPLEMENT`, `VERIFY`,
`INTEGRATE`, `SYNCHRONIZE`, or `CLEANUP`. Two descriptors with the same kind
but different applicability identities are different boundaries.

## Identity

Boundary identity binds:

- repository identity;
- Development Intent identity;
- Current State stateIdentity;
- captureId when capture freshness matters;
- Authority Set identity;
- normalized obligation identities;
- boundary kind and exact objective;
- allowed mutation and changed-path surface;
- required inputs and preconditions;
- expected outputs and verification;
- exclusions and stop condition;
- successor rules;
- boundary-contract version.

## Bounded preparation

**Bounded preparation** may inspect evidence, establish Development Intent,
resolve the Authority Set, normalize obligations, construct a Current State
Record, project sufficient context, and issue one pending Boundary Descriptor.

Preparation cannot perform or claim completion of the development boundary it
describes.

## Bounded continuation

**Bounded continuation** consumes one pending Boundary Descriptor and applicable
receipts, performs exactly that boundary, and returns a Collaboration Result.

Continuation may preserve completed valid work and repair the smallest failed
operation within the pending boundary. It cannot:

- select another issue;
- broaden changed paths or mutation authority;
- redefine objective, exclusions, or acceptance;
- replace the Authority Set;
- weaken normalized obligations;
- substitute another Current State identity without explicit re-preparation;
- perform integration, synchronization, or cleanup unless that responsibility
  is the described boundary.

If applicability is lost, continuation stops the dependent operation and
reports the mismatch. It does not silently redefine the pending boundary.

## Separate responsibilities

Integration, synchronization, and cleanup use separate Boundary Descriptors and
receipts.

A successful integration does not prove synchronization. Synchronization does
not authorize cleanup. Cleanup cannot erase immutable evidence, accepted
history, or required recovery material.
