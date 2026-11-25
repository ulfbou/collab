# Chat Collaboration Model

**Status:** Proposed normative specification
**Document type:** Chat collaboration specification
**Repository:** `ulfbou/collab`
**Path:** `docs/specifications/chat-collaboration-model.md`
**Architecture:** `docs/architecture/collaboration-model.md`
**Implementation status:** Target behavior requiring migration

## 1. Purpose

This specification defines Collab's target chat-facing operating model. It governs ordinary-chat-first use, the primary collaboration chat, user-mediated role chats, criteria for opening a new chat, one active user obligation, artifact movement between chats, and safe continuation in a replacement chat.

This specification does not replace Collab's durable semantic model. The governing sequence remains:

Development Intent
→ Authority Set
→ normalized obligations
→ Current State Record
→ Boundary Descriptor
→ bounded continuation
→ Receipt and Collaboration Result
→ Result Acceptance
→ accepted State Transition

Evidence, authority, decisions, results, and receipts provide inputs to Result Acceptance. Only successful Result Acceptance creates an accepted State Transition and advances durable Collab workflow state.

## 2. Current compatibility workflow

The ordinary-chat-first model in this specification is target behavior requiring migration. Current Collab behavior continues to support:

- explicit Lead and Senior profiles;
- separate Lead and Senior bootstrap packages;
- fixed Lead-to-Senior and Senior-to-Lead movement;
- `nextConversation` values of `LEAD`, `SENIOR`, or `NONE`;
- role-specific output contracts; and
- instructions requiring the user to act as courier between Lead and Senior conversations.

Lead and Senior remain supported compatibility workflows until the ordinary-chat-first workflow and proportionate role separation are implemented, validated, and accepted.

Existing profiles, package names, output headings, return packages, and `nextConversation` values remain valid. Existing scripts must not be changed merely to rename responsibilities. Removal or consolidation requires a separately accepted migration boundary.

## 3. Target operating model

### 3.1 Human-directed and non-agentic

Collab is a human-directed, non-agentic collaboration method:

- the user retains product authority;
- the user creates or returns to chats and transfers artifacts;
- chats perform bounded responsibilities;
- no chat autonomously creates, invokes, delegates to, supervises, or controls another chat;
- no chat infers acceptance or converts a recommendation into accepted state; and
- mechanisms execute accepted authority but do not possess lifecycle authority.

### 3.2 Ordinary-chat-first use

An ordinary AI chat is the target default Collab interface. The user should not need to understand scripts, schemas, revision identifiers, integrity hashes, or internal state projections merely to collaborate on a development task.

The current chat continues by default. It applies as much or as little Collab structure as the task requires and translates internal mechanisms into plain-language user actions.

### 3.3 Primary collaboration chat

The primary collaboration chat is the ordinary chat where work normally begins and continues. It may interpret the request, resolve applicable authority, prepare bounded work, inspect evidence, prepare a handoff, identify a decision, and state the next safe action.

It does not own the portfolio, lifecycle, acceptance, completion, or canonical truth. It cannot grant itself or another chat authority. It need not remain permanently available because a replacement chat may resume from validated continuation evidence.

### 3.4 Responsibilities are not mandatory personas

Lead, Senior, review, recovery, and evidence evaluation identify bounded responsibilities, authority limits, and expected results. A responsibility name does not by itself require a separate chat.

One chat may perform multiple compatible responsibilities when independence is unnecessary, no authority conflict exists, the user has not required separation, and the artifact and evidence boundaries remain clear.

A separate chat is mandatory only when the criteria in section 4 require separation.

## 4. Criteria for opening a new chat

A new role chat is justified only when at least one of the following applies:

1. **Independence is required.** The result must be evaluated without relying on the producing chat's reasoning or assumptions.
2. **Authority separation is required.** Proposal, implementation, review, or acceptance must remain distinct.
3. **Context specialization is materially beneficial.** A bounded package gives the receiving chat clearer or safer context than the accumulated conversation.
4. **Context replacement or recovery is required.** The current chat is unavailable, unreliable, overloaded, or must be replaced.
5. **Stale-result protection is required.** Baseline and revision identity must be frozen across asynchronous work.
6. **Parallel work has been explicitly authorized.** Bounded tasks may proceed without overlapping authority or mutation scope.
7. **A required validation scenario demands role separation.** For example, an implementation result requires independent review.

A new chat must not be required merely because a named role exists, a lifecycle phase changed, an internal script or schema exists, the task is large, or a separate chat would make Collab appear more structured.

## 5. User-mediated role chats

When a separate chat is justified, Collab must tell the user in plain language:

- whether to create or return to a named role chat;
- which responsibility that chat adopts;
- which exact artifact or coherent file set to upload;
- the exact start instruction;
- what result the chat must return;
- where the returned result must go;
- whether a user decision is required; and
- the next safe action.

The user performs the handoff. The receiving chat operates only within the assignment and returns the defined result or a defined blocked result.

## 6. One active user obligation

Every boundary response must identify one active user obligation. The obligation may be to make one decision, upload one named artifact or coherent file set, open one specified chat, run one provided operation, return one result, provide one evidence package, or stop at the authorized boundary.

One obligation means one coherent action. It may involve several explicitly named files when those files together form one handoff. For example, uploading exactly three files produced by `collab-chat-kickstart.sh` is one handoff obligation, not three simultaneous obligations.

Later conditional steps may be described, but they must not be presented as additional current obligations.

## 7. Handoff envelope

A handoff under the new chat-collaboration contract must define:

### Current chat

- responsibility;
- lifecycle responsibility;
- permitted decisions.

### Trigger

- exact condition requiring a new chat;
- why the current chat must not perform that responsibility.

### User action

- create or return to the named role chat;
- upload the exact artifact or coherent file set;
- provide the prescribed start instruction.

### Input artifact

- filename pattern;
- artifact type;
- producer;
- required contents;
- validation requirements;
- baseline and revision identity.

### Receiving chat

- responsibility;
- bounded assignment;
- permitted operations;
- prohibited operations.

### Required result

- filename pattern;
- required contents;
- completion criteria;
- failure or blocked-result format.

### Return route

- destination chat;
- import or validation action;
- stale-result handling.

### Decision gate

- whether user authority is required;
- exact decision requested;
- decision artifact or recorded acceptance;
- consequences of accept, reject, or revise.

### Next action

- continue here;
- open another role chat;
- run a local Collab operation;
- provide missing evidence; or
- stop at the authorized boundary.

## 8. Artifact routing and compatibility

Cross-chat artifacts created under the new chat-collaboration contract must identify, directly or through validated references:

- collaboration or work-item identity;
- artifact type;
- producing responsibility;
- intended receiving responsibility;
- baseline identity;
- specification or contract version;
- revision or attempt identity;
- creation time where operationally relevant;
- integrity identifier where stale or altered artifacts matter;
- permitted use;
- required return artifact; and
- terminal, superseded, or reusable status.

Existing Lead and Senior artifacts remain valid compatibility artifacts until their schemas and producers are migrated. Current workflows must not be declared non-conformant merely because they do not yet implement the complete routing envelope.

A receiving chat operating under the new contract must return a blocked result when it is not the intended receiver, required authority is absent, baseline identity cannot be established, the artifact is stale or superseded, required inputs are missing, or the requested operation exceeds the assignment.

## 9. Mapping to existing durable contracts

The chat model must use existing Collab contracts before introducing a new artifact type.

| Proposed concept | Existing Collab contract |
|---|---|
| Authority artifact | Development Intent and Authority Set |
| Boundary artifact | Boundary Descriptor |
| Evidence artifact | Repository observations and Current State Record |
| Handoff artifact | Existing chat-start manifest and Lead/Senior packages |
| Result artifact | Collaboration Result |
| Receipt artifact | Receipt |
| Acceptance artifact | Result Acceptance |
| Durable transition | State Transition |
| Continuation artifact | Existing bounded continuation/package behavior |

A new artifact may be introduced only when the accepted compatibility specification proves that no existing contract satisfies the requirement.

## 10. Result Acceptance and durable state

Chat activity may prepare, continue, implement, evaluate, or route work, but it does not itself advance durable Collab state.

Evidence, authority, decisions, results, and receipts provide inputs to Result Acceptance. Only successful Result Acceptance creates an accepted State Transition and advances durable Collab workflow state.

Lead and Senior outputs remain proposals, implementation results, evidence, or continuation inputs according to their existing contracts. They do not gain transition authority through this specification.

## 11. Proportionality

Collab must use the least ceremonial workflow that still protects authority, evidence, preservation, continuation, required independence, consequential operations, and stale-result detection.

A workflow is non-conformant under the target model if it requires extra chats, artifacts, decisions, schemas, or commands without protecting one of those properties.

Routine exchanges within one chat do not require artifacts merely for procedural completeness. An artifact is justified when it protects continuation, baseline or revision identity, durable acceptance, consequential authorization, independently verifiable evidence, stale-result detection, or recovery from conversational loss.

## 12. Schema migration

New or materially revised schemas must identify their governing specification and provide requirement traceability. Existing schemas must be assessed and migrated through the compatibility plan without changing their accepted semantics incidentally.

Schemas are executable projections of accepted prose contracts. They must not introduce independent requirements or silently redefine the existing durable semantic model.

## 13. Operation boundaries

This specification distinguishes:

1. **Candidate creation inside an accepted implementation boundary.** Candidate files may be created or modified without a new authorization for every file write when the work remains inside the accepted Boundary Descriptor.
2. **Application to the user's authoritative local repository.** Applying changes requires the applicable accepted boundary and must preserve its scope and invariants.
3. **Explicit consequence operations.** Commit, push, pull-request creation or update, merge, publish, release, deployment, deletion, or accepted-state transition requires explicit consequence authority and a Receipt or equivalent execution proof.

This distinction must not weaken existing mutation gates or repository-local authority.

## 14. Continuation and replacement chats

A replacement chat may resume only from validated continuation evidence sufficient to establish applicable authority, current accepted state, current Boundary Descriptor, baseline and revision identity, completed and outstanding work, returned Results and Receipts, Result Acceptance status, stale or superseded artifacts, and the next safe action.

Continuation must preserve the distinction between what was intended, authorized, attempted, observed, proven, accepted, and transitioned.

## 15. Migration boundary

No implementation of the new ordinary-chat-first model, complete handoff envelope, or role migration may begin until its governing specification and compatibility boundary are accepted. Existing roadmap increments and unrelated implementation may continue under their existing accepted authority.

The migration must preserve:

- existing Lead and Senior profiles;
- existing package names;
- existing output headings and return packages;
- existing `nextConversation` values;
- existing preparation, bounded continuation, Result Acceptance, and State Transition semantics; and
- existing scripts unless a separately accepted migration boundary requires a behavioral change.

## 16. Acceptance criteria for this specification

This specification is ready for acceptance when it is confirmed to:

- preserve the existing durable semantic model;
- mark ordinary-chat-first behavior as a migration target rather than current implementation;
- preserve Lead and Senior compatibility explicitly;
- define a testable threshold for opening a new chat;
- define one coherent active user obligation;
- map proposed artifact concepts to existing contracts;
- make the complete routing envelope prospective;
- make schema traceability prospective;
- preserve Result Acceptance as the only durable transition point; and
- avoid blocking existing accepted roadmap work.
