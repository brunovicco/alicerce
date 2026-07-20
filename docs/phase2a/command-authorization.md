# Trusted Pre-Spawn Command Authorization

Status: Implemented
Decision date: 2026-07-20

## Scope

This increment adds a pure trusted authorization step between command planning
and the executor port. It creates no process, opens no filesystem path, resolves
no executable, and performs no network operation.

`CommandRequest` now carries the complete immutable `RunIdentity` and rejects a
workspace whose run or baseline differs. This preserves the run's contract and
policy identities through the command boundary rather than relying on a bare
workspace capability alone.

`CommandPolicy` binds the run-pinned `PolicyHash`, the canonical
`loop_schemas.models.Actions` object, and an ordered tuple of exact trusted
`CommandRule` values. Alicerce reexports `Actions` by object identity and does
not define an equivalent local serialized model.

## Exact rules

Each rule identifies one permitted combination of:

- semantic action;
- logical executable identifier;
- complete argv argument tuple;
- normalized workspace-relative directory;
- permitted environment-variable names;
- deny-all network policy;
- maximum timeout, termination grace, stdout, and stderr ceilings.

Rules are unique and sorted. Their actions must occur in canonical
`Actions.allowed` and must not occur in `Actions.denied`. Requests cannot select
an arbitrary executable mode through arguments because argv must match a
trusted rule exactly. Template arguments are deferred until they have their own
bounded grammar and tamper tests.

## Mandatory authorization order

`authorize_command` checks policy identity, canonical action authority, exact
executable and arguments, working directory, environment authority, network
policy, and ceilings. A denial raises `CommandAuthorizationError` with a stable
typed cause.

The application use case `execute_authorized_command` completes authorization
before invoking `CommandExecutorPort`. The port now accepts only an
`AuthorizedCommand`, not a raw request. Tests use a counting executor to prove
that every denied request leaves the invocation count at zero.

`AuthorizedCommand` revalidates its rule during construction, so callers cannot
substitute a stale or weaker rule after authorization.

## Policy hash correspondence

This increment verifies that the configured command policy carries the same
`PolicyHash` already bound into `RunIdentity`. It does not yet define canonical
serialization for the complete trusted policy bundle or recompute that bundle's
hash from command rules alone. Command rules are only one part of the future
bundle, alongside usage trust, gates, retention, and review policy.

The trusted policy loader must later construct all components from one exact
bundle and verify their correspondence before a run begins. This known gap does
not permit runtime hash drift, but it keeps full policy provenance partial.

## Acceptance impact

A06 gains executable evidence that denied actions, executables, arguments,
working directories, environment authority, and limits fail before executor
invocation. Network authority is deny-only by construction. A06 remains partial
until a real adapter proves the same ordering immediately before process spawn.

A03 remains satisfied for the already persisted run identity; command requests
now preserve that identity. Full policy-source correspondence remains a future
strengthening rather than a relaxation of resume validation.

A07 remains open until a local adapter enforces timeout and process-tree
cleanup. A08 remains open until output, environment, candidate, specification,
and evidence hashes are assembled. A19 remains protected.

## Explicit exclusions

This increment does not implement:

- subprocess creation, shells, or executable discovery;
- local workspace-path resolution;
- filesystem or network sandboxing;
- timeout, cancellation, or process-tree cleanup;
- argument templates or candidate-controlled command fragments;
- trusted gate execution;
- evidence, verdict, artifact, provider, or observability behavior;
- merge, deployment, release, hosting, or GitHub mutations.
