# Local Command Execution Coordination

Status: Implemented
Decision date: 2026-07-20

## Scope

`LocalCommandExecutor` coordinates an already authorized command with the
private local workspace mapping, a pinned executable registry, and an
adapter-private process-sandbox seam. This increment intentionally provides no
real process backend and imports no subprocess facility in production code.

The separation prevents a portable subprocess wrapper from claiming network or
filesystem isolation that it cannot enforce. A future platform backend must
prove those properties independently and fail closed when unavailable.

## Workspace execution lease

`LocalGitWorkspace` now exposes one concrete-adapter execution lease used only
by trusted local coordination. The method is absent from and never changes the provider-neutral
`WorkspacePort` and never returns a host path to domain or application code.

The lease:

- accepts an exact `WorkspaceIdentity` capability;
- holds the workspace lock for its complete lifetime;
- validates mapping, root, Git metadata, baseline, remotes, and symlinks before
  yielding the path;
- blocks concurrent snapshot and release operations;
- repeats the full validation after coordination, including exceptional exits.

The initial lock is conservative and serializes local workspace operations.
Per-workspace leases are deferred until their concurrency and recovery
invariants have dedicated tests.

## Trusted executable registry

`TrustedExecutable` maps one logical `ExecutableId` to an absolute, regular,
executable, non-symlink file. Construction resolves the path strictly and
records its SHA-256 digest. The coordinator rechecks path integrity, executable
permission, and content immediately before and after sandbox invocation.

No `PATH` lookup, shell string, alias, inherited shell configuration, or
candidate-selected executable path is supported. A remaining verify-to-exec
race must be closed by the future platform backend through its native execution
and confinement mechanism.

## Coordination flow

For every call, `LocalCommandExecutor`:

1. accepts only `AuthorizedCommand`;
2. repeats trusted authorization;
3. resolves the logical executable from the pinned registry;
4. requires the backend to declare support for `NetworkPolicy.DENY_ALL`;
5. obtains the private workspace execution lease;
6. resolves a real directory inside the workspace without symlink traversal;
7. constructs an adapter-private invocation with only the explicit environment;
8. delegates to the sandbox seam;
9. rechecks the executable and workspace;
10. converts the bounded backend result into `ExecutionResult`.

Unknown workspaces, changed executables, unsupported network policy, invalid
working directories, backend failures, malformed results, and post-execution
workspace corruption fail with stable `CommandExecutionErrorCause` values.

## Adapter-private sandbox seam

`ProcessSandboxBackend` is deliberately not reexported as a public Alicerce port. It receives
host `Path` objects only inside `alicerce.adapters.local` and cannot expand core
authority. The production package exports no fake implementation. Deterministic
recording backends exist only in tests.

The seam requires an explicit capability check for network policy and a
shell-free execution method. The next increment must choose platform-specific
backends and demonstrate real timeout, output-ceiling, process-tree, filesystem,
and network behavior.

## Acceptance impact

A06 gains repeated authorization, trusted executable and working-directory
resolution, explicit non-inherited environment, and fail-closed network
capability checks immediately before the sandbox boundary. It remains partial
until a real backend proves denial before process creation.

A04 gains a private execution lease and mandatory post-execution workspace
validation. It remains partial until the child process is confined from trusted
checkout, state, artifact, and gate-driver roots.

A07 remains open because this increment creates no process. A08 remains open
until trusted hashing and canonical evidence assembly are implemented. A19
remains protected.

## Explicit exclusions

This increment does not implement:

- `subprocess`, shell execution, or a production sandbox backend;
- OS-level filesystem or network isolation;
- timeout, cancellation, output capture, or process-tree cleanup against a real
  child process;
- trusted gates, evidence, verdicts, artifacts, budgets, or observability;
- persisted workspace leases or cross-process recovery;
- merge, deployment, release, hosting, or GitHub mutations.
