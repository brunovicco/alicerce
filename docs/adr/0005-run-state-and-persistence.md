# ADR 0005: Run State and Persistence

Status: Accepted
Date: 2026-07-18

## Context

Long-running engineering workflows can be interrupted by process, host,
provider, or infrastructure failures. Recovery must not repeat unsafe side
effects, lose budget accounting, or produce multiple contradictory verdicts.

## Decision

Each run has an immutable `run_id` and immutable bindings to contract ID,
contract version, baseline SHA, and execution policy. State changes are
append-only or compare-and-swap guarded, monotonic, timestamped, and attributed
to the component that requested them.

The internal lifecycle may use non-canonical working states, but every completed
run emits exactly one canonical final state from schemas v0.1.2:
`SUCCEEDED`, `NO_OP`, `NO_PROGRESS`, `VERIFY_FAILED`, `POLICY_BLOCKED`,
`BUDGET_EXCEEDED`, `ESCALATED`, or `INFRA_FAILED`.

Before resume, Alicerce must revalidate:

- contract identity and schema version;
- baseline and candidate identities;
- workspace ownership and integrity;
- persisted evidence hashes;
- budget counters and deadlines;
- whether a verdict already exists;
- whether the next operation is idempotent.

A verdict write is single-assignment. Conflicting retries fail closed and
escalate. Non-idempotent provider or external operations require an idempotency
key or cannot be automatically resumed.

Run artifacts are persisted through an `ArtifactStore` separate from builder
tools. A required retention policy defines per-run and global storage ceilings,
maximum age by artifact class, abandoned-run handling, and full-storage
behavior. Automated cleanup is idempotent, produces an audit record, never
removes active-run artifacts, and preserves evidence referenced by a verdict.

The orchestrator schedules lifecycle evaluation; the `ArtifactStore` enforces
policy atomically. A missing or invalid retention policy fails closed before a
run begins.

## Consequences

- Runs can recover without silently replaying completed work.
- Persistence becomes part of the trusted computing boundary.
- Storage implementations require concurrency and corruption tests.
- Cleanup must preserve evidence according to retention policy.

## Rejected alternatives

### Keep lifecycle state only in process memory

Rejected because interruption would lose authority, budgets, and recovery data.

### Infer state from telemetry

Rejected because telemetry may be sampled, delayed, duplicated, or unavailable.

### Re-run the entire workflow after every failure

Rejected because it can repeat side effects and exceed budgets.

## Acceptance conditions

- Crash-recovery tests cover every operation boundary.
- Duplicate delivery cannot create a second verdict.
- Corrupt or mismatched state fails closed.
- Resume never changes immutable run bindings.
- Every terminal path maps to one canonical final state.
- Cleanup tests cover active, abandoned, terminal, and verdict-referenced runs.
- Full storage and invalid retention policy produce typed fail-closed outcomes.
