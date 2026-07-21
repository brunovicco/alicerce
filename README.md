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

## Trusted pre-spawn authorization

`CommandRequest` now preserves the complete run identity and must agree with its
workspace run and baseline. `CommandPolicy` combines the run-pinned policy hash,
the canonical contract `Actions`, and exact trusted command rules.
`execute_authorized_command` rejects changed policy identity, denied actions or
executables, altered argv, working-directory changes, excess environment
authority, and raised ceilings before invoking `CommandExecutorPort`.

The executor port accepts only `AuthorizedCommand`. Counting-executor tests
prove denied requests produce zero port calls. No process or filesystem adapter
is introduced by this increment; A06 remains partial until the local adapter
repeats the checks immediately before spawn.

## Local command execution coordination

`LocalCommandExecutor` now repeats authorization, resolves a pinned executable,
obtains a private workspace execution lease, resolves a non-symlink working
directory, supplies only the explicit environment, and delegates to an
adapter-private sandbox seam. Executables and workspace integrity are rechecked
after the backend returns.

The coordinator contains no subprocess implementation. A backend that cannot
enforce the deny-all network policy is rejected before invocation. A04 and A06
gain local coordination evidence but remain partial, and A07 remains open until
a platform backend demonstrates real confinement, timeout, output ceilings, and
process-tree cleanup.

## Linux process sandbox

`LinuxProcessSandboxBackend` is the first platform-specific implementation of
the private process-sandbox seam. It pins an explicitly configured `bubblewrap`
binary, probes the required namespace support, denies network access, exposes
only read-only system runtime files plus the writable candidate workspace,
clears the environment, captures bounded output, applies a wall-clock timeout,
and terminates the sandbox process group.

The adapter fails closed when the kernel or runner cannot create the requested
sandbox. It does not provide a macOS fallback. A dedicated Ubuntu conformance
job now requires the real namespace capability and runs adversarial checks for
network denial, workspace-only persistent writes, explicit environment,
timeout, and descendant cleanup. A04, A06, and A07 are demonstrated for this
supported Linux profile; cross-platform confinement and A08 evidence bindings
remain outside this increment.

## Controlled baseline materialization

The first filesystem/process primitive uses a constrained Git CLI to create an
independent local clone at an exact detached baseline. It disables inherited
Git configuration, prompts, hooks, and non-file protocols, removes the remote,
and exposes no generic command method. Typed verification and temporary-index
tree snapshot operations support the local workspace adapter; untrusted command
execution remains a separate increment.
