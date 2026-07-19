# SQLite State Store

Status: Implemented
Decision date: 2026-07-19

## Scope

`SQLiteStateStore` is the first durable local implementation of
`StateStorePort`. It uses only Python's standard-library `sqlite3` module and
introduces no runtime dependency.

The adapter owns persistence mechanics only. It does not decide when a run may
resume and does not perform external identity, workspace, evidence, budget, or
idempotency validation.

## Canonical state format

Run identities, checkpoints, and lifecycle transitions use versioned canonical
UTF-8 JSON bytes with:

- format version `1` and an artifact-specific format identifier;
- lexicographically ordered object keys;
- compact separators and no insignificant whitespace;
- UTC timestamps with exactly six fractional digits and a `Z` suffix;
- strict rejection of duplicate keys and nonstandard JSON constants;
- exact field sets with no ignored extensions;
- reconstruction through the existing immutable domain types.

Decoding rejects malformed UTF-8, malformed or noncanonical JSON, unknown
formats or versions, invalid domain values, and data that cannot be encoded
back to the exact input bytes.

The serialization format is local Alicerce state, not a replacement for the
canonical serialized contracts and final-state vocabulary owned by
`engineering-loop-schemas`.

## SQLite schema v1

The database uses `PRAGMA user_version = 1` and two strict tables:

- `alicerce_runs` stores the immutable identity and current checkpoint;
- `alicerce_transitions` stores one immutable event per run and revision.

The identity column is written only during exclusive initialization. Transition
rows have a composite primary key of run ID and revision and a foreign key to
the run.

A new empty database is initialized transactionally. Schema versions other than
zero or one fail closed as `corrupt`. This increment defines no migration path.
The supplied parent directory must already exist, and `:memory:` is rejected
because a durable filesystem database is required by this adapter.

## Transaction and CAS behavior

Initialization and updates use `BEGIN IMMEDIATE`. A successful update performs
the following within one transaction:

1. load and validate the persisted identity, checkpoint, and complete journal;
2. compare the reconstructed checkpoint with the caller's complete expected
   checkpoint;
3. append exactly one transition;
4. update the checkpoint with a SQL byte-equality precondition;
5. commit both writes together.

A stale or identity-changed caller receives `conflict`. A failure between the
append and checkpoint update rolls back both changes. Concurrent attempts from
the same checkpoint therefore produce exactly one accepted update.

## Corruption handling

Every load, history read, and CAS reconstructs the run from its immutable
identity and ordered transition journal. Validation rejects:

- invalid or noncanonical identity, checkpoint, or transition bytes;
- identity, lookup key, and checkpoint disagreement;
- missing or repeated revisions;
- transitions that do not form an allowed monotonic lifecycle;
- a current checkpoint that differs from the reconstructed history;
- unsupported schema versions.

These failures surface as `StateStoreErrorCause.CORRUPT`. SQLite access,
constraint, lock-timeout, and filesystem failures surface as
`StateStoreErrorCause.STORAGE_FAILURE`. Neither cause is converted into a
successful or missing-state result.

## Acceptance impact

A03 gains durable immutable identity storage and whole-checkpoint CAS. It
remains partial until resume compares the persisted binding with freshly
validated contract, baseline, and policy inputs.

A11 gains transactional checkpoints, an append-only journal, persistence across
process instances, concurrency control, rollback evidence, and fail-closed
corruption detection. It remains partial until resume revalidates every
identity, artifact, counter, deadline, verdict, and idempotency boundary.

A10 is unchanged because verdict persistence and single assignment are not part
of this state schema.

## Explicit exclusions

This increment does not implement:

- schema migration beyond initial v1 creation;
- resume orchestration or crash-boundary replay decisions;
- candidate, workspace, evidence, budget, verdict, or review state;
- `ArtifactStorePort` or retention;
- runner, subprocess, workspace, or provider behavior;
- observability, A2A, MCP, or OpenTelemetry;
- merge, deployment, release, or other repository mutations.
