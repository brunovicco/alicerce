# State Store Contract

Status: Accepted
Decision date: 2026-07-19

## Decision

Trusted run state is represented by an immutable `RunCheckpoint` containing the
complete `RunIdentity` and current `RunLifecycle`. A `StateUpdate` binds one
expected checkpoint to exactly one attributed lifecycle transition and its
resulting checkpoint.

`StateStorePort` is a structural, provider-neutral persistence boundary with
four operations:

1. `initialize` exclusively creates the identity-derived `CONTRACT_BOUND`
   checkpoint at revision zero and fails with `already_exists` when the run is
   present;
2. `load` returns the current checkpoint or `None` when absent;
3. `compare_and_append` atomically appends one transition and replaces the
   current checkpoint only when the stored checkpoint equals the complete
   expected checkpoint;
4. `history` returns accepted transitions as an immutable tuple in revision
   order and fails with `not_found` for an absent run.

The compare-and-swap precondition deliberately includes the immutable run
identity, lifecycle state, revision, timestamp, and canonical final state. A
caller cannot pass a matching revision while silently changing the contract,
baseline, policy, or other checkpoint facts.

Store implementations must expose the stable operational causes
`already_exists`, `not_found`, and `conflict`. They must never append an event
or change the current checkpoint after a failed precondition.

## Validated invariants

- identity, expected lifecycle, transition, and resulting lifecycle refer to
  the same `RunId`;
- lifecycle time never precedes identity creation;
- each update advances exactly one revision;
- transition states connect the expected and resulting snapshots;
- transition time never regresses and equals the resulting snapshot time;
- transition and resulting snapshot carry the same canonical final state;
- the next checkpoint preserves the complete expected `RunIdentity`.

## Acceptance impact

A03 gains an executable whole-checkpoint identity precondition for concurrent
state changes. It remains partial until a durable adapter and resume path
revalidate persisted identities.

A11 gains the provider-neutral checkpoint, CAS, and ordered-history contract
needed for recovery. It remains open until persistence, serialization, crash
boundaries, and resume validation are implemented.

A10 is unchanged because verdict construction and single-assignment verdict
persistence remain outside this increment.

## Explicit exclusions

This increment does not implement:

- SQLite, filesystem, or any concrete state-store adapter;
- checkpoint or transition serialization;
- migrations, locking, transactions, or crash recovery;
- resume orchestration or idempotency validation;
- verdict, evidence, artifact, or review persistence;
- workspace or subprocess execution;
- providers or observability;
- merge, deployment, or release capabilities.

The in-memory implementation used by the executable contract tests exists only
under `tests/` and is not part of the Alicerce runtime package.
