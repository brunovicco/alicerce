# Alicerce

Alicerce is the vendor-neutral foundation for deterministic, auditable,
evidence-gated engineering loops used by Python engineering harnesses.

## Current status

The Phase 2 Design Gate and Phase 2A readiness review are approved. Incremental
implementation of the trusted local core is authorized against the mandatory
Phase 2A acceptance matrix.

The current implementation establishes package boundaries, deterministic
quality gates, canonical schema integration, immutable run identity types, and
exact-byte contract binding. It also defines a pure monotonic run lifecycle
policy with immutable snapshots and attributed transition events, plus an
immutable checkpoint and compare-and-swap state-store contract. A local SQLite
adapter now provides canonical state serialization, transactional append-only
history, whole-checkpoint CAS, and fail-closed corruption detection. It does
not implement an autonomous runner, full resume orchestration, candidate
promotion, merge, deployment, provider adapters, or observability integration.

## Architectural direction

- canonical contracts remain owned by `engineering-loop-schemas`;
- evidence and verdict artifacts remain the technical source of truth;
- the shared core remains independent of Codex, Claude, and other providers;
- telemetry is operational context, never authoritative evidence;
- human approval remains required for promotion, merge, and deployment;
- failure handling is explicit, deterministic, resumable, and fail-closed.

The proposed `a2a-otel-kit` integration is an optional observability adapter. It
will not be a mandatory dependency of the core.

## Related repositories

- `brunovicco/engineering-loop-schemas`
- `brunovicco/codex-python-engineering-harness`
- `brunovicco/claude-python-engineering-harness`
- `brunovicco/a2a-otel-kit`

## Implementation scope

Only Phase 2A is authorized. Phase 2B integrations and every repository,
promotion, merge, deployment, and release mutation remain outside the core's
authority.

## Contract identity

`RunIdentity` accepts a `BoundContract` derived from exact UTF-8 JSON bytes. The
binding includes the canonical `Contract`, the original bytes, and their
SHA-256 digest; direct construction revalidates their correspondence. Resume
identity validation independently rechecks contract ID/version/hash, baseline,
and policy against durable state. A03 is satisfied. A08 remains open until
evidence integrity bindings are implemented.

## State persistence boundary

`RunCheckpoint` binds the complete immutable identity to the current lifecycle.
`StateUpdate` validates one revision, event, and resulting snapshot before a
store sees it. `StateStorePort` requires exclusive initialization, whole-
checkpoint compare-and-swap, and append-only ordered history.

`SQLiteStateStore` implements that boundary with schema-versioned canonical
JSON, atomic journal/checkpoint updates, persistence across process instances,
and full-history validation on every read. `load_run_for_resume` rejects changed
contract, baseline, or policy bindings and terminal runs before returning a
checkpoint. A11 remains partial until resume also validates candidate and
workspace identity, artifacts, counters, deadlines, verdict state, and
idempotency.

## Workspace capability boundary

`WorkspaceIdentity` binds an opaque `WorkspaceId` capability to a run and its
baseline without exposing a filesystem path. `CandidateIdentity` adds a
semantically distinct complete candidate SHA. `WorkspacePort` defines trusted
prepare, load, snapshot, and idempotent release operations.

`LocalGitWorkspace` now implements this boundary with a private in-process
capability mapping, standalone baseline clones, protected-root and symlink
checks, deterministic tree snapshots, and safe quarantined release. A04 remains
partial until future candidate commands receive OS-level confinement. A08
remains open until candidate and environment identities are bound into
authoritative evidence.

## Controlled command execution boundary

`CommandRequest` now binds a workspace capability to a logical executable,
semantic action, argv tuple, normalized relative directory, explicit sorted
environment, deny-all network policy, and hard time and output ceilings.
`CommandExecutorPort` returns a bounded immutable operational result or a typed
failure; a nonzero exit remains data and never becomes a verdict by itself.

This increment intentionally contains no command adapter or generic subprocess
behavior. A06 gains the provider-neutral pre-spawn contract, while A04, A06,
A07, and A08 remain partial or open until a trusted local adapter enforces the
policy and evidence bindings against real processes.

## Controlled baseline materialization

The first filesystem/process primitive uses a constrained Git CLI to create an
independent local clone at an exact detached baseline. It disables inherited
Git configuration, prompts, hooks, and non-file protocols, removes the remote,
and exposes no generic command method. Typed verification and temporary-index
tree snapshot operations support the local workspace adapter; untrusted command
execution remains a separate increment.
