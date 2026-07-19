# Phase 2A Artifact Retention

Status: Proposed

## Ownership

The orchestrator schedules lifecycle evaluation. `ArtifactStorePort` persists
artifacts and enforces retention atomically. Builder capabilities never include
the state or artifact-store root.

A retention policy is required. Missing or invalid policy fails closed before a
run begins.

## Policy fields

The local implementation must configure:

- per-run byte ceiling;
- global byte ceiling;
- maximum age by artifact class;
- abandoned-run threshold;
- minimum preservation for evidence and verdicts;
- full-storage behavior;
- cleanup batch limit;
- audit-record destination.

Numeric production defaults are not embedded in domain code. Tests use explicit
small deterministic policies.

## Artifact classes

- state journal and immutable run identity;
- command metadata and bounded output blobs;
- canonical evidence and verdict;
- local human-review request;
- review-bundle preparation and atomic commit record;
- candidate workspace;
- cleanup audit records.

## Cleanup rules

- active-run artifacts are never removed;
- evidence referenced by a verdict is preserved for its configured period;
- cleanup is idempotent and ordered by policy, not filesystem traversal order;
- candidate workspaces may expire before authoritative evidence;
- abandoned runs receive typed classification before cleanup;
- every deletion produces an audit record without copying deleted content;
- cleanup cannot follow symlinks outside the managed root;
- storage exhaustion cannot evict protected evidence to admit a new run.

## Transactional review bundle

For a run requiring human review, the candidate verdict and local review
request are prepared as one bundle. The request may reference the deterministic
verdict hash, but neither artifact becomes authoritative until an atomic
Artifact Store commit record publishes both.

On resume, an uncommitted prepared bundle is reconstructed from authoritative
evidence. Matching hashes complete idempotently. A mismatch invalidates and
quarantines the preparation with a typed fail-closed outcome. A commit record
with a missing or invalid member is infrastructure corruption and cannot
produce `SUCCEEDED`.

## Full-storage behavior

A new run fails closed when required reservation cannot be made. An active run
that cannot persist required evidence cannot produce `SUCCEEDED`; it resolves
to `INFRA_FAILED` or `ESCALATED` according to recoverability.

## Acceptance criteria

- Quota reservation is atomic under concurrency.
- Symlink and path traversal tests cannot escape the artifact root.
- Active and protected artifacts survive cleanup.
- Abandoned and expired artifacts are cleaned deterministically.
- Cleanup retries do not duplicate or contradict audit records.
- Full-storage tests cannot produce a successful verdict without persisted
  authoritative evidence.
- Crash tests at every review-bundle boundary produce exactly one valid bundle
  or a typed fail-closed outcome, never an authoritative orphan.
