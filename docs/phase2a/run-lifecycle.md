# Phase 2A Run Lifecycle Policy

Status: Accepted
Decision date: 2026-07-19

## Purpose

This policy defines the internal monotonic lifecycle used by Alicerce before a
state store exists. Internal states coordinate trusted work; they are not
canonical final states and must never be serialized as substitutes for the
eight final states owned by `engineering-loop-schemas`.

## Internal states

```text
CONTRACT_BOUND
WORKSPACE_PREPARED
BUILDING
VERIFYING
DECIDING
REVIEW_PENDING
COMPLETED
```

The lifecycle begins at `CONTRACT_BOUND`, revision zero, because a lifecycle is
indexed by the `run_id` that exists only after immutable contract binding. The
normal path then follows the order above. From every non-terminal state, a run
may terminate early in `COMPLETED` when it carries exactly one canonical final
state. `COMPLETED` is terminal and cannot transition again.

## Transition invariants

- Every accepted transition increments the revision by exactly one.
- Time is timezone-aware UTC and cannot regress.
- Every transition is attributed to a validated trusted component identity.
- Snapshots and transition events are immutable and slotted.
- A non-terminal state cannot carry a canonical final state.
- `COMPLETED` and every completion event require exactly one canonical final
  state imported from the pinned schemas package.
- Self-transitions, backward transitions, skips, and post-completion transitions
  fail closed with typed internal causes.

## Persistence boundary

This increment is pure in-memory policy. It does not define `StateStorePort`,
append journals, compare-and-swap behavior, serialization, resume, idempotency,
or verdict single-assignment. Those require a subsequent persistence PR that
stores these immutable snapshots and events without weakening their invariants.

## Acceptance impact

- A03 remains partial until persisted resume revalidates immutable identities.
- A10 remains open until verdict persistence provides single assignment.
- A11 gains a deterministic transition foundation but remains open until state
  persistence and recovery are implemented.
- A12 remains open until every terminal cause is mapped to and tested against
  the canonical final-state vocabulary.
