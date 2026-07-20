# Resume Identity Validation

Status: Implemented
Decision date: 2026-07-20

## Scope

`load_run_for_resume` is the first fail-closed resume use case. It decides only
whether a persisted nonterminal checkpoint still matches the trusted run
bindings supplied by the caller.

The caller must provide:

- the expected `RunId`;
- a `BoundContract` reconstructed from exact validated contract bytes;
- the expected complete `BaselineSha`;
- the expected `PolicyHash`;
- a `StateStorePort` implementation.

The use case does not obtain these values from the persisted checkpoint and
then compare the checkpoint with itself. They are independent trusted inputs
that must be reconstructed before resume is attempted.

## Validation order

The use case loads the checkpoint once and then validates:

1. the run exists;
2. the loaded checkpoint carries the requested run ID;
3. contract ID, contract version, and exact-byte contract hash match the
   supplied `BoundContract`;
4. the persisted baseline SHA matches the supplied baseline;
5. the persisted policy hash matches the supplied policy;
6. the lifecycle is not already `COMPLETED`.

Only a checkpoint that passes every check is returned to the caller. A rejected
resume does not append an event or modify the current checkpoint.

## Typed failures

Identity validation exposes stable `ResumeErrorCause` values:

- `not_found`;
- `run_mismatch`;
- `contract_mismatch`;
- `baseline_mismatch`;
- `policy_mismatch`;
- `terminal_run`.

`StateStoreErrorCause.CORRUPT` and `STORAGE_FAILURE` propagate unchanged. The
use case never converts corrupt or unavailable trusted state into `not_found`
or a resumable checkpoint.

## Acceptance impact

A03 is satisfied for the immutable run bindings defined by `RunIdentity`:

- mutation tests prove the identity values are immutable;
- exact contract bytes are bound to the canonical contract and hash;
- SQLite persists identity separately from mutable checkpoint position;
- whole-checkpoint CAS rejects identity changes;
- resume tests reject changes to contract ID, version, hash, baseline, and
  policy.

A11 remains partial. The use case validates only the trusted bindings currently
represented by `RunIdentity`. Workspace and candidate identity types now exist,
but they are not persisted or revalidated. Workspace integrity, evidence
hashes, budget counters, deadlines, verdict state, prepared review bundles, and
idempotency require later increments.

## Explicit exclusions

This increment does not implement:

- runner or resume orchestration beyond identity validation;
- automatic replay or selection of the next operation;
- candidate or workspace reconstruction;
- evidence, budget, deadline, verdict, or review validation;
- idempotency keys or external side-effect recovery;
- filesystem contract loading;
- subprocess, provider, or observability behavior;
- merge, deployment, release, or repository mutations.
